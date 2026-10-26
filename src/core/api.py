"""The public JSON API, under /api/.

Django Ninja, as PLAN.md's Backend section has it: Pydantic request and response
models and an OpenAPI schema, served at /api/openapi.json, which is what the
front end's TypeScript types are generated from. The interactive docs page is
off: it loads its script from a third-party CDN, which the planned
Content-Security-Policy of `default-src 'self'` would refuse, and the schema is
all a client needs.

No endpoint the map and the planner use needs a sign-in. The owner's decision of
2026-09-26 is that the map and route planning work signed out, and that a signed-out
plan is not saved; so POST /api/route reads the routers and the segment table and writes
nothing but its rate-limit count. What stands in for the sign-in is the per-IP
limit (`core.ratelimit.ROUTING`), applied before the body is read.

The one exception is the road panel's stress editor (OWNER-DECISIONS 441g, 441h;
`core.stress_edits`): GET /api/me, GET /api/stress-edits/way/{id}, POST /api/stress-edits
and POST /api/stress-edits/{id}/undo. They are for an instance admin and are the first
authenticated writes here, so they carry a session, standing, a CSRF token, the same-site
check and per-account counts (see the section at the end of this module).

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

A Bikeshare plan (`preset: "bikeshare"`, `core.bikeshare`) adds two answers of its own, each with
a `code`: 422 `no_bikeshare` where no dock can start or end the ride (no bike of the type, no free
slot, nothing in reach, no way on foot), and 503 `bikeshare_unavailable` with Retry-After where the
operator's station list could not be had. A missing availability feed is not an error: the plan
is made and says availability is unknown.

The two transit ride types (`bike-transit`, `bikeshare-transit`; `core.transit`) answer with a
ranked list of options (`transit.options`: riding the whole way always, the quickest transit
trips, and on Bikeshare + 🚶🚆🚌 walking the whole way where that is reasonable), one of them
planned: the body is its first ride leg and `transit` the rest of the trip,
scheduled. `transit_option` plans another by its key. They add 422 `no_transit` where no option
at all can be made (the sentence says why), and 503
`transit_unavailable` with Retry-After where the deployment has no transit schedule installed
(or, Bikeshare + 🚶🚆🚌, no bikeshare station list).

The checks run in this order, outermost first: the content type and declared
body size, then the per-minute count, then the in-flight slots, then Ninja's
parse and validation. The content type comes before the count on purpose: a
cross-site page can send a `text/plain` or form POST without a preflight, and
counting those would let any page a visitor opens spend that visitor's budget.
A malformed JSON body is counted, because only a script can send one.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from functools import partial, wraps
from typing import Annotated, Literal

from django.conf import settings
from django.db import connections
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from ninja import Field, NinjaAPI, Query, Schema, Status
from ninja.decorators import decorate_view
from ninja.errors import HttpError, ValidationError
from pydantic import (
    ConfigDict,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from routemaker import effort, ridetime
from routemaker.geo import Point, haversine

from . import (
    audit,
    bikeshare,
    climbprofile,
    climbs_near,
    follow,
    gbfs,
    geocode,
    map_match,
    micromobility,
    nearest,
    parallel,
    presets,
    ratelimit,
    route_cache,
    routing,
    scenic_near,
    segment_info,
    share_links,
    stoporder,
    timing,
    trailprofile,
    transit,
    transit_live,
    wmata_bus,
    wmata_live,
    wmata_trains,
)

logger = logging.getLogger(__name__)

# The largest body worth parsing. Twenty-five points with generous precision
# and whitespace is well under 2 KB; Django's own ceiling is 2.5 MB, which is a
# thousand times what this endpoint can use and all of it parsed before the
# point count is checked.
MAX_BODY_BYTES = 8 * 1024
# A route request may also carry an opened file's line to follow (`RouteIn.follow`): its
# encoded text, every character of which JSON may escape as two.
ROUTE_MAX_BODY_BYTES = MAX_BODY_BYTES + 2 * follow.MAX_CHARS

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
    description=(
        "Public route planning for the RouteMaker region. No sign-in, except the road panel's"
        " stress editor (/api/me and /api/stress-edits), which is for instance admins."
    ),
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
BikeName = Literal[presets.BIKE_CLASSIC, presets.BIKE_EBIKE]
EndingName = Literal[bikeshare.ENDING_DOCK, bikeshare.ENDING_OUTSIDE]
# The operator's station id: short text from its own feed, never trusted beyond its length.
StationId = Annotated[str, Field(min_length=1, max_length=64)]


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
            "The hills slider. Every climb costs the extra time it takes; the slider sets the"
            " rider's LT1 grade, past which a steepness penalty adds on: 1% at -100, 8% at 0,"
            " 15% at 100. Above 0 on every"
            ' ride type but Mountain Goat it is "fine with hills": the router\'s routes are'
            " compared that way (two-point plans up to 16 mi (25 km) of straight line;"
            " `hills_tolerate` in the answer). On Mountain Goat above 0 looks"
            " for climbs among the router's alternatives (two-point plans up to 31 mi (50 km)"
            " of straight line). Absent: the preset's own start. Mass Ride stops at 0."
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
    closure_bypass: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list,
        max_length=50,
        description=(
            'v0.7.0, "Route through anyway": the ids of closures (`work_zones.closures[].id`)'
            " the rider chose to route through for this plan. The plan then uses them, and"
            " each is marked `bypassed` on the answer. Never remembered by the server."
        ),
    )
    closures_now: StrictBool = Field(
        default=False,
        description=(
            "v0.9.1, Go and a ride: leave DDOT's occupancy permits off the answer. A permit"
            " says a road may be closed some time in its window, so it is never routed round;"
            " without this it is only flagged on the map (`work_zones.closures`, effect"
            " `possible`), never a description line, a spoken cue or the closure check."
        ),
    )
    blocked_lines: list[Annotated[list[LonLat], Field(min_length=2, max_length=50)]] = Field(
        default_factory=list,
        max_length=10,
        description=(
            'v0.8.2, Ride\'s "Road closed" button: stretches of road the rider found closed on'
            " this ride, each a line of [lon, lat] pairs, left out of the plan as a closure is."
            " Sent with the ride's re-plans only; never remembered by the server."
        ),
    )
    heading: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description=(
            "A ride's re-route: the way the rider is going at the first point, in degrees"
            " clockwise from north. A route that sets off back the other way (a U-turn) is"
            " answered only where it is at least half a mile (805 m) shorter than the best one"
            " that sets off ahead. Absent: either way, as before. Ignored on a followed line,"
            " a loop, Bikeshare and the transit ride types."
        ),
    )
    ride_replan: StrictBool = Field(
        default=False,
        description=(
            "A ride's re-plan: the first point is the rider. On a ride type that does not plan"
            " on dirt trails, a dirt trail there opens them all to this plan (the owner,"
            ' 2026-10-21: "If someone goes onto a dirt trail, any reroutes should include'
            ' dirt"). Elsewhere a dirt trail under a stop, via or end is ridden, with the'
            " trails joined to it, but one under the start alone is not."
        ),
    )
    dirt_ridden: StrictBool = Field(
        default=False,
        description=(
            "With `ride_replan`: the rider has been on a dirt trail this ride (an answer's"
            " `dirt_trails`), so this re-plan may ride any dirt trail wherever the rider is."
        ),
    )
    ahead_only: StrictBool = Field(
        default=False,
        description=(
            "With `heading`: the rider has ridden on past two re-routes' U-turns, so the route"
            " that sets off ahead is answered whatever turning round would save. A U-turn is"
            " still answered where there is no way ahead."
        ),
    )
    dirt_closed: StrictBool = Field(
        default=False,
        description=(
            "With `ride_replan`: the rider marked a dirt trail closed earlier this ride (an"
            " answer's `dirt_closed`), which says its conditions are bad (the owner,"
            " 2026-10-21: \"assume that means bad riding conditions until it's opted back"
            ' in"): this re-plan rides no dirt trail on a ride type that skips them.'
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
    mtb_level: StrictInt | None = Field(
        default=None,
        ge=1,
        le=4,
        description=(
            "Mountain Bike only (docs/MTB-TOPO-PLAN.md, slice 6): the hardest trail level the"
            " rider takes, 1 (green, IMBA 1) to 4 (red, IMBA 4 and up); an unrated"
            " mountain-bike trail counts as 2. A route on a harder trail is answered only where"
            " none can be found without one, with `mtb.over_level_m` saying how much. Absent: 2."
        ),
    )
    mtb_preferred: StrictInt | None = Field(
        default=None,
        ge=1,
        le=4,
        description=(
            "Mountain Bike only (docs/MTB-TOPO-PLAN.md, second pass): the trail level the rider"
            " prefers, 1 to 4. Among the router's routes, trails at it cost least, a level"
            " away a little more, and further away as an unpaved path (never more)."
            " Never above `mtb_level`: a higher one is held to it (`mtb.preferred_level` says"
            " what was used). Absent: 2, or `mtb_level` where that is lower."
        ),
    )
    bike: BikeName | None = Field(
        default=None,
        description=(
            "Bikeshare only (OWNER-DECISIONS 243): `classic` (a few gears, heavier and slower,"
            " hill-averse) or `ebike` (hills barely count, assisted pace). Absent: classic."
        ),
    )
    ending: EndingName | None = Field(
        default=None,
        description=(
            "Bikeshare e-bike only (OWNER-DECISIONS 244): `dock` ends at the nearest dock with a"
            " free slot, `outside_dock` at the destination itself, outside a dock, where the"
            " operator's zone data allows it (otherwise the plan ends at a dock and says why)."
            " Absent: dock."
        ),
    )
    pickup_station: StationId | None = Field(
        default=None,
        description=(
            "Bikeshare only (OWNER-DECISIONS 466a): the id of the station the rider chose to take"
            " a bike from, from POST /api/bikeshare/stations. The plan starts there; if it can no"
            " longer start a ride (no bike of the type, not renting, not reporting) the answer is"
            " 422 `no_bikeshare` saying why. Absent: the nearest docks are tried."
        ),
    )
    dropoff_station: StationId | None = Field(
        default=None,
        description=(
            "Bikeshare only (OWNER-DECISIONS 466a): the id of the station the rider chose to"
            " return the bike to. The plan ends there, with the same refusal as `pickup_station`."
            " Not with the `outside_dock` ending. Absent: the nearest docks are tried."
        ),
    )
    depart_at: datetime | None = Field(
        default=None,
        description=(
            "Transit ride types only: when the trip starts, ISO 8601 (with an offset, or local"
            " time in Washington), within a year of now. Absent: now. Each system's own"
            " calendar for that day is used, holidays and published closures included."
        ),
    )
    transit_option: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9>-]+$",
        description=(
            "Transit ride types only: the `key` of one of the answer's `transit.options`, to plan"
            " that option (its route line, steps and total). Absent, or no longer an option: the"
            " quickest."
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

    novice_legs: StrictBool = Field(
        default=False,
        description=(
            "Transit ride types only (v0.7.0, Novice and Nervous): plan the bike legs as Novice"
            " and Nervous does, every road read one level of traffic stress up, so the page can"
            " offer Own bike + Transit and Bikeshare + Transit beside a Novice and Nervous route"
            " that still uses LTS 3 or worse (its `novice.transit`)."
        ),
    )
    novice_hop: list[LonLat] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description=(
            "With `novice_legs` (v0.11.0): where the Novice route's busiest stretch begins and"
            " ends (its `novice.busiest` `from` and `to`). The transit trips also board near"
            " the first and get off near the second, so one can ride, hop a train or bus past"
            " the stretch, and ride on; the quickest such trip is planned unless"
            " `transit_option` asks for another, and is marked `hop`."
        ),
    )
    quick: StrictBool = Field(
        default=False,
        description=(
            'v0.7.0, "Faster routing": answer the first good route at once - the router\'s own'
            " route with its closures, stress and description, and no search after it - marked"
            " `provisional`. The client then asks again without it for the full plan and swaps"
            " that in where it is better (Go, before Start only). Ignored where a first route"
            " cannot be shown alone (a loop, a long ride or long calm plan, Mountain Bike,"
            " Bikeshare and the transit ride types): the full plan is answered, not provisional."
        ),
    )
    candidates: StrictBool = Field(
        default=True,
        description=(
            "False answers the plan's route alone: no routes to choose from are looked for"
            " (`candidates` and `rank` are null), so a re-plan answers sooner and smaller."
            " Ride mode sends it on every re-plan, which uses only the first route (review"
            " speed-5). The route itself is planned as with true."
        ),
    )
    via_points: list[StrictInt] = Field(
        default_factory=list,
        max_length=MAX_POINTS,
        description=(
            "v0.7.0, via points vs stops: the indices into `points` of the via points, which only"
            " shape the route. The route passes each without a U-turn or a stop; every other"
            " point is a stop. Never the first or the last point. Absent: every point is a stop,"
            " as before."
        ),
    )
    follow: str | None = Field(
        default=None,
        min_length=2,
        max_length=follow.MAX_CHARS,
        description=(
            "An opened file's line to follow exactly, encoded as Valhalla's polyline at precision"
            f" 6: at most {follow.MAX_POINTS:,} points inside the coverage area and 124 mi (200"
            " km) long. The route is then the router's match of that line on the ride type's"
            " graph, split into legs at `points` (each at the line's nearest vertex), with no"
            " search beside it; where the ride type cannot ride the line, the router's own way"
            " joins the parts it can (`follows_file`). Ignored on a loop and the two-point ride"
            " types. A line past those limits, or that matches no way at all, is planned"
            " through `points` instead. Where the line breaks the ride type's rules the route"
            " keeps to them and goes round, unless `follow_exact`."
        ),
    )
    follow_exact: bool = Field(
        default=False,
        description=(
            "The manual mode of `follow`: the line is followed as ridden, against one-way"
            " traffic, through restricted turns and along ways closed to bicycles (a road the"
            " police close for a parade). False (the default): the route keeps to the ride"
            " type's rules and goes round where the line breaks them. Ignored without `follow`."
        ),
    )

    straight_legs: list[StrictInt] = Field(
        default_factory=list,
        max_length=MAX_POINTS,
        description=(
            "v0.9.1, Plan's manual mode: the legs the rider drew, by index (leg i runs from"
            " `points[i]` to `points[i + 1]`). Each is the straight line between its points,"
            " ridden as drawn, its stress unknown; the other legs are routed as asked. The"
            " route is then the rider's own: no routes to choose from, calm search or detour"
            " check (`drawn_legs`). Ignored on a loop, with `follow`, and on the two-point ride"
            " types."
        ),
    )

    @field_validator("preset", mode="before")
    @classmethod
    def _renamed_ride_types(cls, value):
        """An old ride type's name (a link or a saved plan from before it was renamed) plans
        as the ride type it became: "kids" is Novice and Nervous (v0.7.0)."""
        return presets.resolve_preset(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def dials_fit_the_preset(self):
        preset = presets.PRESETS[self.preset]
        if self.via_points:
            last = len(self.points) - 1
            if len(set(self.via_points)) != len(self.via_points) or any(
                not 0 < index < last for index in self.via_points
            ):
                raise ValueError(
                    "via_points are distinct indices of points between the start and the end"
                )
        if self.straight_legs:
            last = len(self.points) - 1
            if len(set(self.straight_legs)) != len(self.straight_legs) or any(
                not 0 <= index < last for index in self.straight_legs
            ):
                raise ValueError("straight_legs are distinct indices of legs between the points")
        if self.novice_legs and self.preset not in presets.TRANSIT_PRESETS:
            raise ValueError("novice_legs applies to the transit ride types only")
        if self.novice_hop is not None and not self.novice_legs:
            raise ValueError("novice_hop goes with novice_legs")
        if self.hills is not None and self.hills > 0 and not preset.hills_seek:
            raise ValueError(
                "Mass Ride does not look for climbs: a field that slows below balance speed on a"
                " climb walks, so the hills slider stops at the fastest time"
            )
        if self.mtb_level is not None and self.preset != presets.MOUNTAIN_BIKE:
            raise ValueError("mtb_level applies to the Mountain Bike ride type only")
        if self.mtb_preferred is not None and self.preset != presets.MOUNTAIN_BIKE:
            raise ValueError("mtb_preferred applies to the Mountain Bike ride type only")
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
        if self.assist and (
            preset.assist_speed_kmh is None or self.preset in presets.BIKESHARE_PRESETS
        ):
            raise ValueError("assist applies to the Cargo Bike ride type only")
        if self.preset in presets.TRANSIT_PRESETS:
            if len(self.points) != 2:
                raise ValueError(
                    "Transit ride types take a start and an end: the bike legs, Metro and bus"
                    " are planned from those two points"
                )
            if self.loop:
                raise ValueError("Transit ride types do not plan loops")
        elif self.transit_option is not None or self.depart_at is not None:
            raise ValueError("transit_option and depart_at apply to the transit ride types only")
        if self.preset in presets.BIKESHARE_PRESETS:
            if len(self.points) != 2:
                raise ValueError(
                    "Bikeshare plans take a start and an end: the walk, the ride between docks"
                    " and the walk are planned from those two points"
                )
            if self.loop:
                raise ValueError("Bikeshare does not plan loops")
            if self.ending == bikeshare.ENDING_OUTSIDE and (self.bike or "classic") != "ebike":
                raise ValueError("only an e-bike can end outside a dock")
            if self.dropoff_station and self.ending == bikeshare.ENDING_OUTSIDE:
                raise ValueError("a chosen drop-off station means ending at a dock")
            if self.preset == presets.REBALANCE and self.ending == bikeshare.ENDING_OUTSIDE:
                raise ValueError("Rebalance Ride ends at a station that needs bikes, a dock")
        elif (
            self.bike is not None
            or self.ending is not None
            or self.pickup_station is not None
            or self.dropoff_station is not None
        ):
            raise ValueError(
                "bike, ending, pickup_station and dropoff_station apply to Bikeshare and"
                " Rebalance Ride only"
            )
        return self

    @field_validator("depart_at")
    @classmethod
    def _depart_near_now(cls, value: datetime | None) -> datetime | None:
        return near_now(value)

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

    @field_validator("novice_hop")
    @classmethod
    def hop_inside_coverage(cls, points: list[list[float]] | None) -> list[list[float]] | None:
        """A hop outside the area (an edited link) is left out, not refused: the trip is
        still planned, without it."""
        west, south, east, north = settings.COVERAGE_BBOX
        for lon, lat in points or ():
            if not (west <= lon <= east and south <= lat <= north):
                return None
        return points

    @field_validator("follow")
    @classmethod
    def followable(cls, encoded: str | None) -> str | None:
        # Only text that is no line at all is refused; a line that cannot be followed (too
        # long, too many points, partly outside the area) is planned through `points`
        # instead (`_follow_line`), as a route always was.
        if encoded is not None:
            try:
                routing.decode_polyline6(encoded)
            except (IndexError, ValueError, TypeError):
                raise ValueError("follow is not a line encoded at precision 6") from None
        return encoded


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


# How far from now a trip's time may be (`depart_at`, `at`): a time near the year 1 or 9999
# overflowed in the time zone's conversion and answered 500 (review api-5).
WHEN_RANGE = timedelta(days=366)


def near_now(value: datetime | None) -> datetime | None:
    """`value` where it is within WHEN_RANGE of now (a time without an offset is local time
    in Washington); otherwise a refusal, which the API answers 400."""
    if value is None:
        return None
    at = value if value.tzinfo is not None else value.replace(tzinfo=ridetime.ZONE)
    try:
        if abs(at - timezone.now()) <= WHEN_RANGE:
            return value
    except OverflowError:
        pass
    raise ValueError("the time must be within a year of now")


BusyCode = Literal["long_ride_timed_out", "bikeshare_unavailable", "transit_unavailable"]


class BusyOut(Schema):
    error: str
    code: BusyCode | None = Field(
        default=None,
        description=(
            "`long_ride_timed_out`: a long ride ran out of its time budget: show it, and do not"
            " resend it without the rider asking. `bikeshare_unavailable`: the operator's station"
            " list could not be had. `transit_unavailable`: a transit ride type's schedule (or"
            " its bikeshare station list) is not available."
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
    rough: bool | None = Field(
        default=None,
        description=(
            "On an unpaved section: whether its surface is natural or rough (dirt, grass, a"
            " rutted track; the route line draws it brown) or not (gravel, drawn grey); null:"
            " not known (drawn brown), and on every paved or unknown section."
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


class HillClimbOut(Schema):
    """A categorised climb the route rides uphill (FOLLOWUP-HILL-SEEK, OWNER-DECISIONS
    205), from the Climbs layer's file (`core.hillseek`)."""

    id: str = Field(description="The climb's id in the Climbs layer's file.")
    category: Literal["5", "4", "3", "2", "1", "HC"]
    length_m: int
    gain_m: int = Field(description="Net height gained, metres.")
    grade_pct: float = Field(description="Average grade, percent to a tenth.")
    from_m: int = Field(description="Where the route reaches its foot, metres along.")
    to_m: int = Field(description="Where the route reaches its summit, metres along.")
    unpaved: bool
    name: str | None = Field(description="The long trail carrying most of it, if any.")
    text: str = Field(
        description='In words, US units first: "Category 4 climb, 0.8 miles (1.3 km) at'
        ' 5.0%, 262 ft (80 m) gained".'
    )
    sought: bool = Field(description="Whether the hill seek asked the router for it.")


class HillClimbSeekOut(Schema):
    """What the hill seek did (`core.hillseek`, FOLLOWUP-HILL-SEEK, OWNER-DECISIONS 205)."""

    near: int = Field(description="Climbs inside the distance budget's corridor.")
    asked: int = Field(description="Router calls made for routes through them.")
    found: int = Field(description="Routes found, added to those compared.")
    limited: Literal["no_climbs", "time"] | None = Field(
        description=(
            "`no_climbs`: this host has no Climbs layer file, so only the router's own"
            " alternatives were compared; `time`: the seek's time ran out."
        )
    )


class HillsSeekOut(Schema):
    """Present when the hills slider was past its detent on Mountain Goat, the one ride
    type where that seeks climbs (FOLLOWUP-HILLS-TOLERATE, OWNER-DECISIONS 242)."""

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
    climbs: list[HillClimbOut] = Field(
        default_factory=list,
        description="The categorised climbs the kept route rides uphill, in order (205).",
    )
    climb_seek: HillClimbSeekOut | None = Field(
        default=None,
        description=(
            "The hill seek: routes through the climbs near the line, compared with the"
            " router's own (205); null where it did not run."
        ),
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
    """Present when the hills slider was below its detent: the router's alternatives
    weighed with each climb at its real time plus a steepness penalty past the LT1 grade
    the slider sets (`routemaker.hill_cost`), and brake-riding descents."""

    candidates: int = Field(description="Routes compared, the router's own included.")
    chosen: int = Field(description="Which was kept; 0 is the router's own route.")
    weight: float = Field(description="How much the brake-riding descent cost counted: -hills/100.")
    brake_grade: float | None = Field(
        description="The ride type's grade past which a descent costs; null: never."
    )
    grade_cost_s: float = Field(
        description=(
            "The kept route's climbing and descent cost, in the router's cost seconds, over its"
            " cost with the router's own climbing charge taken off (`routing.hill_s`)."
        )
    )
    direct_grade_cost_s: float = Field(description="The same for the router's own route.")
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


class HillsTolerateOut(Schema):
    """Present when the hills slider was past its detent on a ride type where that means
    "fine with hills" (every one but Mountain Goat; FOLLOWUP-HILLS-TOLERATE, OWNER-DECISIONS
    242): the router's routes compared with each climb at its real time and a steepness
    penalty only past the LT1 grade the slider sets, 8% to 15% (`routemaker.hill_cost`)."""

    candidates: int = Field(description="Routes compared, the router's own included.")
    chosen: int = Field(description="Which was kept; 0 is the router's own route.")
    weight: float = Field(description="The slider's position over 100.")
    discount_s: float = Field(
        description=(
            "The steepness penalty the detent would charge the kept route and this position"
            " does not, in the router's cost seconds; 0 at the top of the stress slider"
            " (`calm_first`)."
        )
    )
    extra_climb_m: float = Field(description="The kept route's climb over the router's own.")
    extra_distance_m: float
    limited: Literal["two_points", "long_ride", "timed_out", "calm_first"] | None = Field(
        description=(
            "Why no alternatives were compared, if none were. `calm_first`: at the top of"
            " the stress slider, where the stress order decides and its distance level"
            " already counts no climbing."
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
    crossed_tier: int | None = Field(
        description=(
            "The crossed road's LTS on the map, 1-5; null if unknown. Below 3 only where"
            " the junction read a multi-lane road by its traffic, not its bike lane."
        )
    )
    movement: Literal["left", "straight", "right"]
    control: Literal["signal", "stop", "cross_stop", "all_stop", "none"]
    kind: str
    cost_ft: int = Field(description="The model's cost, in feet of equivalent quiet riding.")
    calm_mi: float | None = Field(
        default=None,
        description="The same cost in calm miles, 2 places (467); `calm_km` is the metric.",
    )
    calm_km: float | None = None
    time_band: Literal["weekday_rush", "weekend", "night"] | None = Field(
        default=None,
        description=(
            "The ride time that changed this junction's cost (468a, 469c-469e): more at"
            " weekday rush hours, less at the weekend or at night; null where the hour"
            " changed nothing (off-peak, a cap that holds at any hour, a rated junction)."
            " The planner says it in words."
        ),
    )
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
    Trailmaxxing and Cargo with passengers: OWNER-DECISIONS 250), `doubles_back`
    (it rides out along a way and back again, more than 164 ft (50 m) beyond what the
    route it would replace does), `too_long`, `unread` or `no_route`."""

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
            " router's first route, OWNER-DECISIONS 250), `too_long`, `not_worth`, `overlap`"
            " or `unread`; null where nothing was"
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
            "Rides with the LTS 4 hold only (OWNER-DECISIONS 250): metres of LTS 4 and"
            " Avoid on the router's own route, which the search never exceeds: the rated"
            " metres, not hill-weighted (OWNER-DECISIONS 409, `refine.rated_lts4_m`)."
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


class DescriptionShapeOut(Schema):
    """The ways at an unusual junction, in degrees from straight ahead as the rider
    arrives, clockwise positive, -180 to 180."""

    out: int = Field(description="The way the route takes.")
    others: list[int] = Field(description="Every other way, drawn dashed.")
    main: Literal["before", "after"] | None = Field(
        default=None,
        description=(
            "On a turn onto a service road beside a main road: the main road lies across the"
            " way in (crossed just before, as for a left) or across the way ahead (a right"
            " short of it)."
        ),
    )
    ring: Literal["right", "left"] | None = Field(
        default=None,
        description=(
            "On the way off a circle: drawn as a ring, entered bearing right (round it"
            " anticlockwise) or left; `others` are then the exits passed."
        ),
    )


class DescriptionExitOut(Schema):
    """The way off a circle (`describe.circle_exit`)."""

    number: int = Field(description="The exit taken, counting the streets off the ring passed.")
    circle: str | None = Field(description="The circle's name; null where it has none.")


class DescriptionTurnOut(Schema):
    """How the rider comes into a described stretch, or what a junction entry
    is: the movement, the street turned onto, who has the right of way where
    the junction model read the junction, and its severity where it flagged it."""

    movement: Literal["left", "straight", "right", "bear_left", "bear_right"] | None = Field(
        description="Null where the router gave no headings and no junction event did."
    )
    onto: str | None = Field(description="The street turned onto; null on a junction entry.")
    control: Literal["signal", "stop", "cross_stop", "all_stop", "none"] | None = Field(
        description="Null where the junction model did not read the junction."
    )
    severity: Literal["orange", "red"] | None = Field(
        description='"Higher stress" (orange) or "Very high stress" (red), where flagged.'
    )
    stay: bool | None = Field(
        default=None,
        description='A fork along one way: "Bear right to stay on ..."; absent elsewhere.',
    )
    shape: DescriptionShapeOut | None = Field(
        default=None,
        description=(
            "An unusual junction's shape, which the ride card draws in place of its plain"
            " arrow (`describe.junction_shape`); absent at a plain crossroads or T."
        ),
    )
    exit: DescriptionExitOut | None = Field(
        default=None,
        description='Off a circle: "Take the 3rd exit onto ... at Dupont Circle Northwest".',
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
    `bicycle=dismount` connector; OWNER-DECISIONS 291(5)); an `avoid` is an
    Avoid-rated junction ahead (307), at a point, its `severity` "avoid"; a
    `workzone` is a live work zone the route runs along (FOLLOWUP-WORKZONES, 341-349),
    its `severity` "red" for a closure and "orange" for a zone with a penalty, or, at
    0 with no severity, the work-zone disclaimer or the feeds that could not be read;
    a `climb` is a categorised climb the route rides uphill where the hill seek ran
    (FOLLOWUP-HILL-SEEK, 205), from its foot to its summit; a `hazard` is a known road
    hazard the route rides (v0.10.0: cobblestones, rails in the road; `core.route_hazards`).
    Distances are along the route, scaled to `distance_m`. `text` is one plain
    sentence, US units first with the metric once, for reading aloud; the other
    fields are the same facts for a client that words them itself. Additive:
    older clients ignore it, and it is null where it could not be built."""

    kind: Literal["stretch", "junction", "via", "walk", "avoid", "workzone", "climb", "hazard"]
    from_m: int
    to_m: int
    from_mi: float
    to_mi: float
    street: str | None = Field(
        description="The street, an unnamed bike lane's name from the street beside it (\"9th"
        ' Street Northwest protected bike lane"), or "path" or "unnamed road"; null on a `via`'
        " and where a junction's road has no name."
    )
    tier: int | None = Field(description="1-5 on a stretch; null: not rated, or not a stretch.")
    facility: Literal["path", "protected", "lane"] | None = Field(
        description='The bike facility, where there is one; "none" and unknown are null.'
    )
    turn: DescriptionTurnOut | None = Field(
        description="How the stretch is entered, where it begins at a change of street."
    )
    severity: Literal["orange", "red", "avoid"] | None = None
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
    citation: str | None = Field(
        default=None,
        description=(
            'On a "workzone": its source and until when ("Source: DDOT permits, until'
            ' Nov 14."), shown in small text under `text` and never read out (v0.8.2);'
            " null elsewhere."
        ),
    )
    text_lanes_hidden: str | None = Field(
        default=None,
        description=(
            "On a stretch: `text` with painted lanes on LTS 4 and Avoid not called bike "
            'lanes, for the client switch "Show bike lanes on high-stress roads" '
            "(OWNER-DECISIONS 275); null where that is `text`."
        ),
    )
    relation_name: bool = Field(
        default=False,
        description=(
            "On a stretch: its `street` is its trail's route relation's name, carried by "
            "no way of it itself; the ride gives no cue for a change onto such a name."
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
    cruise_pace_ms: float | None = Field(
        default=None,
        description=(
            "The group's cruising pace, m/s (`routemaker.flow.CRUISE_PACE_MS`, 7 mph): with"
            " `level_riders_per_min`, the group's length at a ride size (PLAN items 128, 139)."
        ),
    )
    default_level_riders_per_min: float | None = Field(
        default=None,
        description=(
            "The level figure of the road a group's length is read on where no width is"
            " known anywhere on the route (`flow.GROUP_DEFAULT_WIDTH_M`, two 11 ft lanes)."
        ),
    )


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
    oneway: bool | None = Field(
        default=None,
        description=(
            "The crossed or joined road is one-way there (one approach to hold: 1 corker,"
            " PLAN item 139), two-way (false: 2), or not known (null)."
        ),
    )
    divided: bool | None = Field(
        default=None,
        description=(
            "A divided road: its two one-way carriageways counted as one junction, so two"
            " approaches to hold (2 corkers) whatever `oneway` says."
        ),
    )
    approach_lanes: int | None = Field(
        default=None,
        description=(
            "Through lanes on each approach of the crossed or joined road (per direction; a"
            " divided road's busier carriageway), if known: the chart holds one corker an"
            " approach lane where no signal holds the cross traffic, and one an approach at a"
            " signal (PLAN item 139)."
        ),
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
    window that holds them (at the top of the slider, the worth rule's exchange). Each road
    counts at its own routing cost over the local quiet street's (`calm.quiet_factor`), so
    about 1.0 is all quiet-street riding; a path or a protected lane counts below it. Every
    ride type but Mass Ride."""

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
            "Where the words change, read from representative roads at their own cost at"
            " this ride's slider position (`calm.bands`; LTS 1-2 below the first, LTS 3 to"
            " the second, LTS 4 above)."
        )
    )
    estimate: bool = Field(
        description=(
            "False where every road is priced by its own routing cost (its own speed, lanes"
            " and cycle lane, as the router costs it); true where some stretch took its"
            " tier's figure instead (the middle of the tier's modelled range), as a trace"
            " with no edge attributes does, or where the live tier and the graph disagree"
            " about grading (a stress edit since the last rebuild)."
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
    level_riders_per_min: list[int | None] | None = Field(
        default=None,
        description=(
            "Mass Ride only: the level riders a minute at each sample, from the width alone"
            " (`flow.level_riders_per_min`), so the front end can read the group's length at"
            " each point; null where the width is unknown or the stretch is marked Avoid."
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


class BikeshareStopOut(Schema):
    """A dock, a free-floating e-bike or the destination, as the plan uses it."""

    kind: Literal["dock", "free_bike", "outside_dock"]
    name: str
    lon: float
    lat: float
    station_id: str | None = Field(default=None, description="The operator's id for a dock.")
    availability: Literal["known", "unknown"]
    bikes_available: int | None = Field(
        description="Bikes of the chosen type at the dock; null: unknown or not a dock."
    )
    classic_available: int | None = None
    ebikes_available: int | None = None
    docks_available: int | None = Field(description="Free slots; null: unknown or not a dock.")


class BikeshareWalkOut(Schema):
    """A walk leg (Valhalla pedestrian costing)."""

    geometry: LineString
    distance_m: float
    duration_s: float
    to: str = Field(description="Where it goes: a dock's name, or `your destination`.")


class WalkInOut(Schema):
    """The walks at a route's ends where the ride stops short of the point asked (the
    owner, 2026-10-17: a memorial a bike is walked through; `routing.walk_in`)."""

    start: BikeshareWalkOut | None = Field(
        default=None, description="From the start asked to where the ride begins."
    )
    end: BikeshareWalkOut | None = Field(
        default=None, description="From where the ride ends to the end asked."
    )


class BikeshareFeeOut(Schema):
    name: str
    price: str = Field(description="As the operator publishes it, a decimal string.")
    currency: str
    description: str = Field(description="The operator's own words for the plan.")


class BikeshareEndingOut(Schema):
    """One way to end the ride (OWNER-DECISIONS 244). An E-bike has two: the dock, and the
    destination outside a dock where the operator's zone data allows it."""

    kind: Literal["dock", "outside_dock"]
    offered: bool
    chosen: bool = Field(description="Whether this plan ends this way.")
    reason: str | None = Field(
        description=(
            "Why an ending is not offered: `no_zone_data`, `zones_unreadable`,"
            " `no_parking_zone` or `classic_bikes_end_at_docks`."
        )
    )
    reason_text: str | None
    fee: BikeshareFeeOut | None = Field(
        description=(
            "The out-of-dock fee, read from the operator's pricing plans, never assumed; null"
            " where no plan names one. Information, not a quote."
        )
    )
    fee_text: str | None
    walk_m: float | None = Field(description="The walk from the dock to the destination.")
    text: str


class BikeshareStepOut(Schema):
    kind: Literal["walk", "ride"]
    text: str


class BikeshareOptionEndOut(BikeshareStopOut):
    """One end of a route option: the stop, its walk, and how much riding it adds."""

    walk_m: float = Field(description="The walk to (or from) it; 0 for an outside-dock ending.")
    walk_s: float
    extra_m: float = Field(
        description=(
            "The riding it adds, straight-line metres: how much farther it is from the trip's"
            " other end than the rider's own point is, never below 0."
        )
    )
    on_the_way: bool = Field(description="It adds under 165 ft (50 m) of riding.")
    way_text: str = Field(
        description='"on your way", or "adds 0.2 mi (0.3 km) of riding": the reason, in words.'
    )


class BikeshareOptionOut(Schema):
    """One way to make the trip, a pick-up and a drop-off, quickest first, from docks chosen
    by the walk plus the extra riding each adds (stations on your way first; the owner,
    2026-10-11)."""

    rank: int = Field(description="1 is the best, and is the plan this answer routed.")
    chosen: bool = Field(description="Whether this answer's route, walks and steps are this one.")
    pickup: BikeshareOptionEndOut
    dropoff: BikeshareOptionEndOut
    pickup_station: str | None = Field(
        description="Send as `pickup_station` on POST /api/route to plan this option."
    )
    dropoff_station: str | None = Field(
        description="Send as `dropoff_station` (null with the `outside_dock` ending)."
    )
    ending: EndingName
    ride_m: float = Field(description="The routed ride when chosen; otherwise an estimate.")
    total_s: float = Field(description="Walking and riding; an estimate unless chosen.")
    estimated: bool
    cost_m: float = Field(
        description="Both walks plus the extra riding (the station lists' rule); breaks ties."
    )
    text: str = Field(description="The option in plain words, US units first, for reading aloud.")


class BikesharePlanOut(Schema):
    """The walks, docks, availability, fee and notes of a bikeshare plan
    (FOLLOWUP-BIKESHARE). The route body around it is the ride leg, dock to dock; the
    walks are here."""

    bike: BikeName
    rebalance: bool = Field(
        default=False,
        description=(
            "Rebalance Ride: picked up at a crowded station (at least 3/4 full) and returned to"
            " one that needs bikes (at most 1/4 full)."
        ),
    )
    ending: EndingName
    start: BikeshareStopOut
    end: BikeshareStopOut
    walk_start: BikeshareWalkOut | None
    walk_end: BikeshareWalkOut | None
    ride_m: float
    ride_s: float
    walk_m: float
    walk_s: float
    total_s: float = Field(description="Walking and riding, without stops.")
    availability: Literal["live", "stale", "unknown"] = Field(
        description="`unknown`: the operator's availability feed could not be read."
    )
    endings: list[BikeshareEndingOut]
    pricing: list[BikeshareFeeOut] = Field(
        description="E-bike: the operator's price plans, as information."
    )
    pricing_note: str | None
    steps: list[BikeshareStepOut]
    summary: str = Field(description="The plan in plain words, US units first, for reading aloud.")
    notes: list[str]
    options: list[BikeshareOptionOut] = Field(
        default_factory=list,
        description=(
            "Up to three pick-up and drop-off pairs, quickest first; the first is this plan."
            " Bikeshare plans only. Another is planned by sending its `pickup_station`,"
            " `dropoff_station` and `ending`; that answer lists only the pair asked for, so keep"
            " this list."
        ),
    )
    credit: str = Field(description="The plain source citation (OWNER-DECISIONS 301).")


class AvoidJunctionOut(Schema):
    """An Avoid-rated junction the route passes (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS
    307-310, 335): rated by a person, never by the model, and rare."""

    id: int
    name: str
    reason: str
    lon: float
    lat: float
    m: int = Field(description="Metres along the route, scaled to `distance_m`.")
    label: str = Field(
        description=(
            'The accessible name of its marker and list row (309): "Avoid-rated junction:'
            ' <name>, <reason>". The skull and crossbones the client draws beside it is'
            " hidden from assistive technology."
        )
    )


class AvoidSearchOut(Schema):
    """What the plan did about Avoid-rated junctions on its route (308, 335). Null where
    the route passes none."""

    passed: int = Field(description="Passes through Avoid-rated junctions the answer still makes.")
    penalty_s: int = Field(description="Their routing penalty, 1,800 cost seconds a pass (308).")
    decision: Literal["kept", "avoided"] = Field(
        description=(
            '"avoided": the way round replaced the route (it cost less than the route plus'
            ' the penalty, or the ride is Mass Ride or Group Ride, 307); "kept": the route'
            " still passes one, and `avoid_alternate` is the way round where one was found."
        )
    )
    alternate: Literal["found", "no_route", "time"] | None = Field(
        description="Whether the way round was found; null once it replaced the route."
    )
    avoided: int = Field(description="Passes the way round took out.")


class MassHazardSpanOut(Schema):
    """A rider-marked hazard on a Mass Ride's route (FOLLOWUP-MASSRIDE-MAP part 3; 325, 326),
    in whole metres along the traced route as `stress_spans` are measured."""

    from_m: int
    to_m: int
    level: Literal["caution", "warning"]
    level_name: str = Field(description='"Caution" or "Warning".')
    words: str = Field(description="The level in plain words.")
    reason: str = Field(description="The reporter's reason, as approved (never their name).")
    road: str


class RoadHazardSpanOut(Schema):
    """A known hazard the route rides (v0.10.0; `core.route_hazards`): cobblestones or rails
    in the road, in whole metres along the traced route as `stress_spans` are measured."""

    from_m: int
    to_m: int
    kinds: list[Literal["cobbles", "rails"]]
    road: str
    text: str = Field(description="One plain sentence, US units first with the metric once.")


class SteepGradeOut(Schema):
    """A steep stretch on a Mass Ride or a Novice and Nervous ride (v0.12.5;
    `routemaker.steep_grades`): past 5% either way ("steep", an orange marker) or 8% ("very_steep",
    red), read in the riding direction, in whole metres along the router's elevation profile."""

    from_m: int
    to_m: int
    direction: Literal["up", "down"]
    level: Literal["steep", "very_steep"]
    grade_pct: int = Field(description="The steepest grade along it, a whole percent, unsigned.")
    text: str = Field(description="One plain sentence, US units first with the metric once.")


class ScenicSpanOut(Schema):
    """A stretch of the route with a scenic designation (v0.12.3; `core.route_scenic`), in
    whole metres along the traced route as `stress_spans` are measured."""

    from_m: int
    to_m: int
    road: str
    designation: str = Field(
        description='As the road panel says it: "Rustic Road (Montgomery County)", several'
        ' joined by " · ".'
    )


class MtbOut(Schema):
    """A Mountain Bike plan's reading of its route (docs/MTB-TOPO-PLAN.md, slice 6;
    `core.mtb`)."""

    max_level: int = Field(description="The hardest trail level held, 1 to 4.")
    preferred_level: int | None = Field(
        default=None,
        description="The preferred trail level used, 1 to 4, never above `max_level`.",
    )
    limited: Literal["time", "untraced", "no_way_round", "no_mtb_graph"] | None = Field(
        default=None,
        description=(
            "Why the rules could not all be held: `time` (the budget ran out), `untraced`, "
            "`no_way_round` (no route without a harder trail was found), `no_mtb_graph` (the "
            "mountain-bike graph is not being served, so the route keeps to the standard graph"
            " and its trails are not weighed)."
        ),
    )
    candidates: int | None = Field(default=None, description="Routes weighed.")
    rounds: int | None = Field(default=None, description="Rounds of excluding harder trails.")
    trail_m: float | None = Field(
        default=None, description="Metres on trail (mountain-bike trails and unpaved paths)."
    )
    singletrack_m: float | None = Field(
        default=None, description="Metres on mountain-bike trails (singletrack)."
    )
    over_level_m: float | None = Field(
        default=None, description="Metres on trails harder than `max_level`; 0 when held."
    )
    long_lts3_m: float | None = Field(
        default=None, description="Metres of LTS 3 in runs of 0.5 mi (805 m) or more."
    )
    lts4_m: float | None = Field(default=None, description="Metres of LTS 4 and Avoid road.")
    easier_m: float | None = Field(
        default=None, description="Metres on trails easier than `preferred_level`."
    )
    harder_m: float | None = Field(
        default=None,
        description="Metres on trails harder than `preferred_level`, up to `max_level`.",
    )
    level_step: float | None = Field(
        default=None,
        description=(
            "The preference's discount step, as a share of a road metre (0.05): a trail metre"
            " counts `trail_weight` less `level_step` x max(0, `level_reach` - levels away from"
            " `preferred_level`)."
        ),
    )
    level_reach: int | None = Field(
        default=None, description="Levels the discount reaches from `preferred_level` (2)."
    )
    trail_weight: float | None = Field(
        default=None, description="What a trail metre counted in the ranking (0.5)."
    )
    singletrack_speed_kmh: float | None = Field(
        default=None, description="The singletrack speed the time is shown at (10 km/h)."
    )
    router_duration_s: float | None = Field(
        default=None, description="The router's own time, before the singletrack speed."
    )


class WorkZoneOut(Schema):
    """A live work zone the route runs along (FOLLOWUP-WORKZONES)."""

    id: str
    kind: Literal["closed", "unknown", "penalty", "lane"] = Field(
        description=(
            '"closed": closed to bicycles (left out where it could be); "unknown": every lane'
            ' closed and bicycles not mentioned (342(3): penalised, with a warning); "penalty":'
            ' rideable, with a heads-up (342(4)); "lane": a bike lane blocked with the road'
            " open (v0.7.0, DDOT permits): a warning only."
        )
    )
    penalty_s: float
    road: str | None
    description: str | None
    reason: str
    from_m: int
    to_m: int
    start: str | None
    end: str | None
    source: Literal["md", "va", "dc", "mpd", "alertdc", "reviewer", "ddot_advisory"]
    warning: bool = Field(description="True for a closure the rider may meet: shown in red.")
    text: str = Field(description="The heads-up as the description words it.")
    bypassed: bool = Field(default=False, description="Routed through: the rider's choice.")
    may_still_apply: bool = Field(
        default=False,
        description="No end given, on a later ride: warned of, not routed round (v0.7.0).",
    )


ClosureEffect = Literal[
    "on_route", "routed_round", "bypassed", "may_still_apply", "possible", "none"
]


class ClosureOut(Schema):
    """A closure drawn on the route's map, and its card (v0.7.0, "Closures on the map")."""

    id: str
    source: Literal["md", "va", "dc", "mpd", "alertdc", "reviewer", "ddot_advisory"]
    source_name: str = Field(
        description='The source as the card names it: "MPD traffic advisory, Oct 15".'
    )
    url: str | None = Field(description="The source's own page.")
    kind: Literal["closed", "unknown", "lane", "penalty"] = Field(
        description='"penalty" (v0.12.0): a rideable work zone, on the map with no route only.'
    )
    severity: Literal["red", "amber"] = Field(
        description=(
            '"red": a closed stretch (a barrier icon); "amber": a bike lane blocked, or'
            " construction that can be ridden through."
        )
    )
    title: str = Field(
        description='What is closed: "Constitution Avenue NW closed, 14th St to 18th St".'
    )
    road: str | None
    when_text: str = Field(
        description='"Closed today 4:30 am to 1:30 pm", "Permit: road closed until Oct 20".'
    )
    start: str | None
    end: str | None
    effect: ClosureEffect = Field(
        description=(
            '"on_route": the route runs along it; "routed_round": the route goes round it;'
            ' "bypassed": routed through by the rider\'s choice; "may_still_apply": on the route,'
            ' no end given on a later ride, not routed round; "possible" (v0.9.1): a DDOT permit,'
            ' flagged only, never routed round; "none": no effect on the route.'
        )
    )
    delay_s: int | None = Field(
        description=(
            "The extra time the detour round it adds on this route (for a bypassed one, the time"
            " going round would add); null where it has none or it was not worked out in time."
        )
    )
    effect_text: str = Field(description='"Detour adds about 4 min", "No effect on your route".')
    can_bypass: bool = Field(description='Whether the card offers "Route through anyway".')
    bypassed: bool
    from_m: int | None = Field(description="Where the route meets it; null where it does not.")
    to_m: int | None
    point: LonLat = Field(
        description="Where its marker goes: the middle of its stretch, or its first point "
        "where the stretch could not be put on the road."
    )
    line: list[LonLat] = Field(
        description="Its stretch along the road; empty where the source gave only its ends "
        "and they could not be put on the road (never drawn as a straight line)."
    )


class ClosureNoticeOut(Schema):
    """A "Check before you go" notice: an NPS park alert, or an advisory that could not be
    placed on the map (v0.7.0). Text and a link; never routed round."""

    id: str
    source: Literal["nps", "mpd", "alertdc", "nps_deer", "mcparks"]
    source_name: str
    title: str
    text: str
    url: str | None
    area: str = Field(
        description='An NPS park code ("rocr"), "dc", or a deer-management closure\'s area'
        ' ("rocr-deer", "moco-G12").'
    )
    area_name: str | None
    point: LonLat | None = Field(description="The park's marker; null for a District-wide notice.")
    category: str | None
    when_text: str


class WorkZonesOut(Schema):
    """The route's work zones and how far they can be trusted (FOLLOWUP-WORKZONES)."""

    on_route: list[WorkZoneOut]
    routed_round: int = Field(
        description="Zones the plan left out: closures, and zones with a penalty it went round."
    )
    status: dict[str, Literal["current", "stale", "unavailable"]]
    stale: list[str]
    unchecked: str | None
    sources: list[str]
    disclaimer: str
    # v0.7.0 ("DC closures source"; "Closures on the map"). Additive.
    ride_at: str | None = Field(
        default=None, description="The ride's moment the zones were matched at."
    )
    closures: list[ClosureOut] = Field(
        default_factory=list,
        description="The closures to draw on the route's map: on it, or in force near it.",
    )
    notices: list[ClosureNoticeOut] = Field(
        default_factory=list, description='"Check before you go": park alerts and unplaced text.'
    )


class RouteBody(Schema):
    preset: PresetName
    variant: Literal["standard", "no-trail", "ebike", "weekend", "offroad", "mtb"]
    # A ride type that does not plan on dirt trails rides one here, as a point on one, or a
    # ride's re-plan, opened it (`core.trail_touch`). A ride sends `dirt_ridden` after one.
    dirt_trails: bool = False
    # Such a ride type's ride marked a dirt trail closed (`blocked_lines`, `dirt_closed`): no
    # dirt trail is ridden, and the ride sends `dirt_closed` for the rest of it.
    dirt_closed: bool = False
    geometry: LineString
    distance_m: float
    # The router's time plus `junction_delay_s`.
    duration_s: float
    # The seconds of `duration_s` the route's junctions add (stops, yields, signals;
    # `routemaker.junction_delay`), which the router's own time leaves out.
    junction_delay_s: float = 0.0
    # Where along the line `duration_s` falls, as [fraction of the length, seconds], hills
    # and junction waits in place (`routemaker.time_marks`), for a ride's arrival times.
    # Null where the router gave no time; the front end then spreads the time evenly.
    time_marks: list[list[float]] | None = None
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
    hills_tolerate: HillsTolerateOut | None = None
    attribution: list[str]
    # Index in geometry.coordinates of each leg's last vertex, one per leg
    # (points - 1); a leg starts where the one before it ends.
    leg_ends: list[int]
    arrival_side: Literal["left", "right"] | None = Field(
        default=None,
        description=(
            "Which side of the street the destination is on, from the router's destination"
            " maneuver (Ride mode's last cue: 'Destination on your right'); null where unknown."
        ),
    )
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
    walk_in: WalkInOut | None = None
    # The Avoid-rated junctions it passes, in route order (FOLLOWUP-ISECT-AVOID, 307-310),
    # and the notice the panel shows first and announces (335). Additive: empty and null
    # where it passes none, which is nearly always (the list ships empty).
    avoid_junctions: list[AvoidJunctionOut] = Field(default_factory=list)
    avoid_notice: str | None = Field(
        default=None,
        description=(
            '"This route goes through an Avoid-rated junction: <name>, <reason>." (335);'
            " null where it passes none."
        ),
    )
    # A Mass Ride's rider-marked hazards it passes, in riding order (FOLLOWUP-MASSRIDE-MAP
    # part 3, 325). Additive: null on every other ride type, empty where it passes none.
    mass_hazards: list[MassHazardSpanOut] | None = None
    # The known hazards it rides (v0.10.0; cobbles, rails), in riding order. Additive: empty
    # where it rides none or the table predates them.
    road_hazards: list[RoadHazardSpanOut] | None = None
    # The scenic designations it rides (v0.12.3; rustic roads, byways, the East Coast
    # Greenway, US Bicycle Routes), in riding order. Additive: empty where it rides none.
    scenic_roads: list[ScenicSpanOut] | None = None
    # Steep grades either way (v0.12.5), in riding order, on a Mass Ride or a Novice and
    # Nervous ride. Additive: null on every other ride type, empty where there are none.
    steep_grades: list[SteepGradeOut] | None = None
    # The Mountain Bike ride type's reading of the route (slice 6). Additive: null on every
    # other ride type.
    mtb: MtbOut | None = None
    # Live work zones (FOLLOWUP-WORKZONES, 341-349). Additive: null where work zones are
    # not running (no refresh stored yet).
    work_zones: WorkZonesOut | None = None
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


class AvoidAlternateOut(RouteBody):
    """The best route round the Avoid-rated junctions the answer passes, however much
    longer (335): a whole route body of its own."""

    extra_distance_m: float = Field(description="How much longer than the answer, metres.")
    extra_duration_s: float = Field(description="How much longer than the answer, seconds.")
    bikeshare: BikesharePlanOut | None = Field(
        default=None,
        description=(
            "Bikeshare only: the answer's walks and docks around this way round, its ride and"
            " totals its own, so it is shown in place of the ride leg with the operator's credit."
        ),
    )


class ClosureThroughOut(RouteBody):
    """The standard way through the closures the answer goes round (v0.8.2): a whole route
    body of its own, drawn beside the answer, which Ride follows where the rider takes it."""

    extra_distance_m: float = Field(description="How much longer than the answer, metres.")
    extra_duration_s: float = Field(description="How much longer than the answer, seconds.")
    closure_ids: list[str] = Field(
        description="The closures (`work_zones.closures[].id`) it goes through."
    )


class TransitStepLiveOut(Schema):
    text: str = Field(
        description='"Live: Red Line toward Shady Grove in 3 min, 11 min."; "Live: bus 52 in 4 min,'
        ' 13 min."'
    )
    minutes: list[int]
    source: Literal["live"] = "live"


class TransitLiveOut(Schema):
    warnings: list[str] = Field(
        description='Elevators out where your bike needs one: "Elevator out at X: carry your'
        ' bike on the stairs."'
    )
    alerts: list[str] = Field(description="WMATA's rail incidents on the lines used.")
    credit: str = Field(description='"Data: WMATA".')
    as_of: str = Field(description="When WMATA was read, local ISO time.")


class TransitStepOut(Schema):
    mode: Literal[
        "ride",
        "take",
        "bikeshare",
        "walk",
        "enter",
        "exit",
        "metro",
        "rail",
        "light-rail",
        "subway",
        "bus",
    ] = Field(
        description=(
            "`ride` your own bike; `take` walk to a bikeshare dock and take a bike; `bikeshare`"
            " ride it and dock it; `walk`; `enter` and `exit` a station; and a transit leg by"
            " its system's mode: `metro` (WMATA), `rail` (MARC), `light-rail`, `subway`, `bus`."
        )
    )
    system: str | None = Field(
        default=None, description='A transit leg\'s system, by name: "Metro", "MARC".'
    )
    departs: str | None = Field(
        default=None,
        description=(
            'An infrequent service (over 15 min apart), or one WMATA predicts (`source` "live"):'
            ' the departure taken, "7:42 am".'
        ),
    )
    source: Literal["scheduled", "live"] | None = Field(
        default=None,
        description=(
            "A transit step's departure: \"live\", WMATA's next train or bus that the rider"
            " reaches the stop in time for (a plan for now; the time on board stays the"
            ' timetable\'s); else "scheduled". Null off transit.'
        ),
    )
    text: str = Field(description="The step in one sentence, US units first, for reading aloud.")
    seconds: int = Field(description="The step's time, without the wait.")
    wait_s: int = Field(
        description="The wait before it: for a service every 15 min or less, half the headway"
        " (a rider who does not time the trip); for a less frequent one, or one timed live, the"
        " time to spare between reaching the stop and the departure taken (`departs`)."
    )
    to: str | None = Field(description="Where the step ends, by name; null: no name.")
    lines: list[str] = Field(description="Metro lines or bus routes that run it.")
    with_bike: bool = Field(description="Your own bike goes too (the elevator, the rack).")
    route_line: bool = Field(
        description="This step is the answer's route line (its geometry is the body's)."
    )
    coordinates: list[list[float]] = Field(
        description=(
            "[lon, lat] for the map: Metro and bus through their stops, walks straight, the far"
            " end's ride as routed; empty for the route line's own step."
        )
    )
    stress_spans: list[StressSpanOut] | None = Field(
        default=None,
        description=(
            "A ride after the route line (own bike or share bike), routed as the route line"
            " is: its sections by traffic stress along `coordinates`, in the form of the"
            " body's `stress_spans`. Null where it was not routed in time (a plain line)."
        ),
    )
    distance_m: float | None = Field(
        default=None,
        description="A ride after the route line, routed: its length, metres. Null otherwise.",
    )
    climb_m: float | None = Field(
        default=None, description="That ride's climb, metres, as the body's `climb_m`."
    )
    descent_m: float | None = Field(
        default=None, description="That ride's descent, metres, as the body's `descent_m`."
    )
    profile: ProfileOut | None = Field(
        default=None,
        description=(
            "That ride's elevation profile, as the body's `profile`, so the trip's chart and"
            " climbs cover every ride. Null where it was not routed in time."
        ),
    )
    live: TransitStepLiveOut | None = Field(
        default=None,
        description=(
            "A Metro step's next trains, or a Metrobus step's next buses, its way now, from"
            " WMATA (core.transit_live, core.wmata_bus)."
        ),
    )


class TransitOptionLegOut(Schema):
    mode: Literal["walk", "ride", "bikeshare", "metro", "rail", "light-rail", "subway", "bus"]
    system: str | None = Field(default=None, description='A transit leg\'s system: "Metro".')
    lines: list[str] = Field(description='Its lines or routes: ["Red Line"], ["C53"].')
    minutes: int


class TransitOptionOut(Schema):
    key: str = Field(description="Send as `transit_option` on POST /api/route to plan it.")
    label: str = Field(
        description='The option in a few words: "Ride, Metro to X (Orange Line), ride".'
    )
    total_s: int
    minutes: int
    direct: bool = Field(description="Riding the whole way (on bikeshare: dock to dock).")
    walk: bool = Field(
        default=False,
        description=(
            "Walking the whole way (Bikeshare + 🚶🚆🚌, where walking is the quickest or the"
            " trip is under 1 mi (1.6 km))."
        ),
    )
    hop: bool = Field(
        default=False,
        description=(
            "Novice and Nervous's hop past the busy stretch (v0.11.0, `novice_hop`): boards near"
            " where it begins and gets off near where it ends."
        ),
    )
    chosen: bool = Field(description="The option this answer plans.")
    busy_m: float | None = Field(
        default=None,
        description=(
            "Its rides' metres on busy roads (LTS 3 and up), said with its time (Stephen,"
            ' 2026-10-21: "arrive in X min with x mi of busy roads"); the options are ranked'
            " by their time with that riding and their junction waits counted again, so the"
            " list need not be in order of time. Null where a ride's roads are not known."
        ),
    )
    elevator_out: bool = Field(
        default=False,
        description=(
            "It takes the rider's own bike through a Metro station whose elevators are all out:"
            " ranked 15 min down, its time unchanged; the row shows the outage (Stephen,"
            " 2026-10-21)."
        ),
    )
    legs: list[TransitOptionLegOut] = Field(
        default_factory=list,
        description=(
            'Its legs compactly, for its row ("🚶 4 min · 🚲 12 min · 🔴 18 min"): walks and'
            " rides with the station's way in or out, a transit leg with its wait."
        ),
    )


class TransitDepartureOut(Schema):
    """The chosen trip's first infrequent departure (the owner, 2026-10-12: "make it clear when
    the next departure would be and if cutting it close, put a timer")."""

    step: int = Field(description="Its index in `steps`.")
    system: str
    vehicle: str = Field(description='"the MARC Penn Line"')
    board_at: str | None = Field(description="The stop boarded, by name.")
    departs: str = Field(description='"7:42 am"')
    departs_at: str = Field(description="ISO 8601, local time with its offset.")
    arrive_at: str = Field(description="When the rider reaches the stop, as planned.")
    next: str | None = Field(description="The departure after it, or null within the hour.")
    next_at: str | None
    spare_s: int = Field(description="Time to spare at the stop, as planned.")
    close: bool = Field(description="Under 5 minutes to spare: Go shows a countdown.")
    planned_at: str = Field(description="The moment the plan is for.")
    point: list[float] | None = Field(description="[lon, lat] of the stop, for the map's label.")
    label: str = Field(description='The map\'s label: "MARC 7:42 am · 6 min spare".')
    source: Literal["scheduled", "live"] = Field(
        default="scheduled", description='"live" where WMATA predicts the departure.'
    )


class TransitOut(Schema):
    """A transit ride type's trip (`core.transit`): scheduled, with WMATA's predicted
    departures on a plan for now (`core.transit_live`)."""

    mode: Literal["bike-transit", "bikeshare-transit"]
    key: str = Field(description="The chosen option's key.")
    direct: bool = Field(description="The chosen option is riding the whole way.")
    total_s: int
    minutes: int
    summary: str = Field(
        description=(
            '"About N min door to door, scheduled.", or "..., with live departures." where'
            " `live_times`."
        )
    )
    bike_only_s: int | None = Field(description="Riding the whole way, for comparison.")
    comparison: str | None
    riding_quicker: bool = Field(description="Riding the whole way is at least as quick.")
    options: list[TransitOptionOut] = Field(
        description=(
            "The options, quickest first (the owner, 2026-10-12): riding the whole way always,"
            " and the quickest transit trip of each kind."
        )
    )
    steps: list[TransitStepOut]
    notes: list[str]
    day_type: Literal["weekday", "saturday", "sunday"]
    band: str | None
    holiday: bool
    bike_blackout: bool = Field(
        description=(
            "Own Bike + 🚆🚌 on a Metro blackout date: no option takes the bike on Metro, and"
            " the notes say so."
        )
    )
    scheduled: bool
    live_times: bool = Field(
        default=False,
        description=(
            "A departure on the chosen trip is WMATA's prediction (its step's `source` is"
            ' "live").'
        ),
    )
    credits: list[str] = Field(description="The schedules' sources, for the systems used.")
    departure: TransitDepartureOut | None = Field(
        default=None, description="The first infrequent departure, or null where there is none."
    )
    live: TransitLiveOut | None = Field(
        default=None,
        description="WMATA's live values on this trip (v0.7.0); null with none to hand.",
    )


class NoviceBusiestOut(Schema):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(description="The road's name, or null where it has none.")
    metres: float
    level: int = Field(description="Its worst real level of traffic stress, 3 to 5 (Avoid).")
    from_: LonLat = Field(
        alias="from",
        description="[lon, lat] where it begins: send it, then `to`, as `novice_hop`.",
    )
    to: LonLat = Field(description="[lon, lat] where it ends.")


class NoviceWalkOut(Schema):
    """A short busy stretch the Novice walks the bike past on the sidewalk beside it (v0.11.0,
    `core.novice_walks`), also a "walk" entry of the directions."""

    from_m: int = Field(description="Where the stretch begins, metres along the route.")
    to_m: int = Field(description="Where it ends, metres along the route.")
    road: str | None = Field(description="The busy road's name; null where it has none.")
    ride_m: float = Field(description="The stretch's length as ridden, metres.")
    geometry: LineString = Field(description="The walk, on foot (pedestrian costing).")
    distance_m: float
    duration_s: float = Field(description="At walking pace beside a bike, in the route's time.")
    text: str = Field(description="The directions' line for it.")


class NoviceOut(Schema):
    busy_m: float = Field(
        description="Metres of real LTS 3 or worse ridden on the route (stretches walked left out)."
    )
    busiest: NoviceBusiestOut | None = Field(
        description="The longest run of LTS 3 or worse, by road; null where there is none."
    )
    over_ceiling: bool = Field(
        description="The calmer routes found were longer than the ride type's 1.4x ceiling."
    )
    transit: bool = Field(
        description=(
            "Offer Own bike + Transit and Bikeshare + Transit beside this route (each requested"
            " with `novice_legs`): it still uses LTS 3 or worse, or is held at the ceiling."
        )
    )
    walked_m: float = Field(
        default=0.0, description="Metres of real LTS 4 or worse walked past instead of ridden."
    )
    walks: list[NoviceWalkOut] = Field(
        default_factory=list,
        description="The short busy stretches walked on the sidewalk beside them, in order.",
    )


class AgainstTrafficOut(Schema):
    name: str | None = Field(description="The street's name; null where it has none.")
    distance_m: float = Field(description="How far the file rides against its traffic, metres.")


class RouteOut(RouteBody):
    follows_file: bool = Field(
        default=False,
        description=(
            "True where the route is the match of the request's `follow` line rather than a"
            " plan through its points; false on every other route, and where a `follow` line"
            " matched no way and the route was planned through the points instead."
        ),
    )
    against_traffic: list[AgainstTrafficOut] | None = Field(
        default=None,
        description=(
            "On a route that follows a file (`follows_file`): the stretches where the file rides"
            " against one-way traffic, in order, which the route goes round (or follows as the"
            " file goes, `follows_exactly`); empty where there are none, null on every other"
            " route and where it could not be read."
        ),
    )
    follows_exactly: bool = Field(
        default=False,
        description=(
            "True where the route follows the file in the manual mode (`follow_exact`), rules"
            " or not; false on every other route."
        ),
    )
    drawn_legs: list[int] | None = Field(
        default=None,
        description=(
            "The legs drawn as straight lines (`straight_legs`, Plan's manual mode), by index;"
            " null on a route with none."
        ),
    )
    provisional: bool = Field(
        default=False,
        description=(
            "True on a first route asked for with `quick`: the router's own route, its closures,"
            " stress and words, before the search (no calm search, candidates, detour check or"
            " Novice offer yet). Ask again without `quick` for the full plan."
        ),
    )
    novice: NoviceOut | None = Field(
        default=None,
        description=(
            "Novice and Nervous only (v0.7.0): how much busy road the route still uses, read on"
            " the real levels, and whether to offer transit beside it; null elsewhere."
        ),
    )
    avoid_search: AvoidSearchOut | None = None
    avoid_alternate: AvoidAlternateOut | None = Field(
        default=None,
        description=(
            "Where the answer still passes an Avoid-rated junction (335): the best route that"
            " avoids it, to offer as an alternate; null otherwise."
        ),
    )
    closure_through: ClosureThroughOut | None = Field(
        default=None,
        description=(
            "Where the answer goes round closures that would otherwise be on it (v0.8.2): the"
            " standard way through them, since a closure marked may not really be closed; null"
            " otherwise."
        ),
    )
    bikeshare: BikesharePlanOut | None = Field(
        default=None,
        description=(
            "Bikeshare only (OWNER-DECISIONS 243-245): the walks, docks, availability, fee and"
            " notes around this body, which is the ride leg between the docks."
        ),
    )
    transit: TransitOut | None = Field(
        default=None,
        description=(
            "Transit ride types only: the whole trip, step by step, around this body, which is"
            " its first ride leg."
        ),
    )
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
    if request.path.startswith(STRESS_EDIT_PATHS):
        # The editor names the field a problem is about, so the form can focus it.
        first = next(
            (
                str(part)
                for error in exc.errors[:1]
                for part in reversed(error.get("loc", ()))
                if isinstance(part, str) and part != "body"
            ),
            None,
        )
        return _stress_error(400, "; ".join(p for p in problems if p) or "invalid request", first)
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
    if request.path.startswith(STRESS_EDIT_PATHS):
        return _stress_error(500, "Something went wrong; nothing was changed.")
    return _error(500, "Something went wrong planning this route.")


# The place-search endpoints, whose unexpected failure is not a route's.
GEOCODE_PATHS = ("/api/geocode", "/api/reverse")
# The road panel's stress editor, whose answers are private and name the form field.
STRESS_EDIT_PATHS = (
    "/api/stress-edits",
    "/api/stress-suggestions",
    "/api/junction-suggestions",
    "/api/mass-hazards",
    "/api/closures/reviewed",
    "/api/closures/reports",
    "/api/closures/stretch",
    "/api/review",
    "/api/me",
)


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


def json_body_up_to(limit: int):
    """`json_body_only` with a larger ceiling for the body (POST /api/route's, which may
    carry a line to follow)."""

    def decorator(view):
        return _json_body_only(view, limit)

    return decorator


def json_body_only(view):
    """Refuse a non-JSON or oversized body before anything counts or parses it."""
    return _json_body_only(view, None)


def _json_body_only(view, limit: int | None):
    """`json_body_only`, the body at most `limit` bytes (None: MAX_BODY_BYTES).

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
        most = MAX_BODY_BYTES if limit is None else limit
        if declared > most:
            return _error(400, f"the body is larger than {most} bytes")
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
    json_body_up_to(ROUTE_MAX_BODY_BYTES),
    errors_as_json,
)
def route(request, body: RouteIn, response: HttpResponse):
    # Where the request's time goes, phase by phase (v0.7.0, "Faster routing" step 1): a
    # Server-Timing header on every answer, and one log line with no location in it.
    timings = timing.Timings(started=timing.now() - _waited_s(request))
    timings.mark("wait")
    token = timing.start(timings)
    try:
        answered = _route_answer(request, body, response)
    finally:
        timing.stop(token)
    header = timings.header()
    if isinstance(answered, HttpResponse):
        answered["Server-Timing"] = header
        status = answered.status_code
    else:
        response["Server-Timing"] = header
        status = getattr(answered, "status_code", 200)
    loop = routing.loop_wanted(body.points, body.loop, body.preset)
    timings.log(body.preset, span_m(routing.loop_points(body.points, loop)), status)
    return answered


def _waited_s(request) -> float:
    """Seconds from the request's arrival (`RequestClockMiddleware`) to now: the `wait`
    phase. Read on the routing clock, at most a minute (gunicorn's own timeout)."""
    started = getattr(request, "routing_started", None)
    if started is None:
        return 0.0
    try:
        # The monotonic clock `routing.clock` reads, read directly: the plan's own budget
        # clock is not advanced by measuring it.
        return min(60.0, max(0.0, float(time.monotonic() - started)))
    except (TypeError, ValueError):
        return 0.0


def _route_answer(request, body: RouteIn, response: HttpResponse):
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


# --- Go's "More direct" and "Calmer" (the owner, 2026-10-16) --------------------------------
#
# POST /api/route/neighbours plans the rider's trip a step more traffic tolerant and a step
# calmer than the rider's own setting (`presets.stress_notches`), for Go to offer beside
# the rider's own route. Go asks once its own route is shown, and never waits on the answer:
# a plan or a ride's re-route asked for meanwhile is sent at once (frontend
# lib/routeScheduler.ts). So this request never takes a slot a plan needs: it has routing's
# deployment slots at the lowest priority and a client slot of its own
# (`ratelimit.NEIGHBOURS_IN_FLIGHT`), and is refused at once when the pool is busy. It counts
# as two routing requests, for the two plans. The plans run one after the other on the
# request's own thread, through the route cache (Bikeshare's ride, between the rider's own
# docks, as a Bikeshare plan is, uncached), inside NEIGHBOURS_BUDGET_S: each plan stops at
# that budget's end (`routing.Deadline`), so nothing outlives the request, and one that fails
# or runs out of time is left out. Nothing is compared here: the page compares each with the
# routes it shows and keeps those that differ enough (frontend lib/neighbours.ts).

# The seconds the two plans may take together, inside the request's own budget.
# 25 since the calmer option became the trailmaxxed route (2026-10-19): the top of the slider
# runs the calm search at its full rate, which took longer than the old notch's one call.
NEIGHBOURS_BUDGET_S = 25
# What the request counts against the routing limit: one for each plan.
NEIGHBOURS_COST = 2


class NeighbourOut(Schema):
    kind: Literal["direct", "calmer"] = Field(
        description=(
            "`direct`: two notches more traffic tolerant. `calmer`: the top of the slider"
            " (Go's Trailmaxxed)."
        )
    )
    stress: int = Field(description="The traffic slider's position it was planned at.")
    route: RouteOut


class NeighboursOut(Schema):
    stress: int = Field(description="The rider's own position, as the notches were read from.")
    options: list[NeighbourOut] = Field(
        description=(
            "Up to two, the more direct first; empty on a ride type that offers neither (Rebalance"
            " Ride, the transit ride types, Mass Ride), at both ends of a ride type's limits, on"
            " a long ride, and on a Bikeshare request that does not name its docks"
            " (`pickup_station`, and `dropoff_station` unless it ends outside a dock): a"
            " Bikeshare option keeps those docks and changes only the ride between them."
        )
    )


@api.post(
    "/route/neighbours",
    response={
        200: NeighboursOut,
        400: ErrorOut,
        422: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        503: BusyOut,
    },
    summary="The same trip more direct and trailmaxxed (Go's route options)",
    by_alias=True,
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.NEIGHBOURS_IN_FLIGHT, slots=ratelimit.neighbour_slots),
    ratelimit.rate_limited(ratelimit.ROUTING, cost=NEIGHBOURS_COST),
    json_body_only,
    errors_as_json,
)
def route_neighbours(request, body: RouteIn):
    stress = _stress_of(body)
    loop = routing.loop_wanted(body.points, body.loop, body.preset)
    if span_m(routing.loop_points(body.points, loop)) > CONFIRM_SPAN_M:
        return Status(200, {"stress": stress, "options": []})
    if body.preset == presets.BIKESHARE and not _same_docks(body):
        return Status(200, {"stress": stress, "options": []})
    direct, calmer = presets.stress_notches(body.preset, stress)
    wanted = [
        (kind, notch)
        for kind, notch in (("direct", direct), ("calmer", calmer))
        if notch is not None
        # A long calm plan takes the long ride's slot and budget: not offered as an option.
        and (
            loop
            or not routing.long_calm_for(
                body.preset, body.points, notch, long_ride=False, trails_off=body.trails_off
            )
        )
    ]
    # The plans' budget runs out NEIGHBOURS_BUDGET_S from now, read as a plan's own budget.
    started = routing.clock() - (routing.PLAN_BUDGET_S - NEIGHBOURS_BUDGET_S)
    bodies = {
        kind: body.model_copy(update={"stress": notch, "quick": False, "candidates": False})
        for kind, notch in wanted
    }
    answered = {kind: _neighbour(bodies[kind], started) for kind, _ in wanted}
    options = [
        {"kind": kind, "stress": notch, "route": answered[kind]}
        for kind, notch in wanted
        if answered.get(kind) is not None
    ]
    return Status(200, {"stress": stress, "options": options})


def _same_docks(body: RouteIn) -> bool:
    """Whether a Bikeshare request names the docks of the rider's own plan, so its options
    vary only the ride between them (the owner, 21:21): the pick-up dock, and the drop-off
    dock unless the ride ends outside one. A plan from a free e-bike has no dock to hold."""
    return body.pickup_station is not None and (
        body.dropoff_station is not None or body.ending == bikeshare.ENDING_OUTSIDE
    )


def _neighbour(body: RouteIn, started: float) -> dict | None:
    """One notch's plan, through the route cache, or None: whatever goes wrong, the option
    is left out. Without the request's timing recorder, as a transit trip's later rides."""
    token = timing.start(None)
    try:
        if body.preset == presets.BIKESHARE:
            # Only the ride between the rider's docks changes (`_same_docks`).
            return _bikeshare_body(body, started)
        return _planned(body, _bike_dials(body), started, False, False)
    except Exception as error:  # noqa: BLE001 - an option never fails the answer
        logger.warning("route neighbours: a notch was not planned: %s", type(error).__name__)
        return None
    finally:
        timing.stop(token)


# --- The nearest stations to pick up from or return to (OWNER-DECISIONS 466, 466a) ---------
#
# POST /api/bikeshare/stations lists the three stations nearest a point that are at least 3/4
# full (to take a bike) or at most 1/4 full (to return one), from the operator's live feed.
# A POST, with the points in the body and not the address, so a visitor's position is in no
# URL or log line; it is used for this one answer and kept nowhere. With `toward` (the trip's
# other end) the stations on the rider's way come first: each is ranked by its walk plus the
# extra riding it adds (`core.bikeshare`'s docstring). The rider chooses, and the plan can be
# asked to use the chosen station (`pickup_station`, `dropoff_station` on POST /api/route).


class NearbyStationsIn(Schema):
    model_config = ConfigDict(extra="forbid")

    point: LonLat = Field(description="[lon, lat]: where the rider will take or return a bike.")
    action: Literal["pickup", "dropoff"] = Field(
        description=(
            "`pickup`: stations at least 3/4 full that are renting. `dropoff`: stations at most"
            " 1/4 full that are taking bikes back."
        )
    )
    toward: LonLat | None = Field(
        default=None,
        description=(
            "[lon, lat]: the trip's other end, the destination for `pickup` and the start for"
            " `dropoff`. Stations on the way come first (each ranked by its walk plus the extra"
            " riding it adds). Absent: by distance alone."
        ),
    )

    @field_validator("point", "toward")
    @classmethod
    def inside_coverage(cls, point: list[float] | None) -> list[float] | None:
        if point is None:
            return None
        west, south, east, north = settings.COVERAGE_BBOX
        lon, lat = point
        if not (west <= lon <= east and south <= lat <= north):
            raise ValueError("the point is outside the area this map covers")
        return point


class NearbyStationOut(Schema):
    station_id: str
    name: str
    lon: float
    lat: float
    percent_full: int = Field(description="Bikes as a percentage of bikes and free docks.")
    distance_m: float = Field(description="Straight line from the point.")
    bikes: int = Field(description="Bikes available, e-bikes included.")
    ebikes: int
    docks: int = Field(description="Free docks.")
    extra_m: float | None = Field(
        default=None,
        description="The riding the station adds, straight-line metres; null without `toward`.",
    )
    on_the_way: bool | None = Field(
        default=None,
        description="It adds under 165 ft (50 m) of riding; null without `toward`.",
    )


class NearbyStationsOut(Schema):
    action: Literal["pickup", "dropoff"]
    availability: Literal["live", "stale", "unknown"] = Field(
        description="`unknown`: the operator's availability feed could not be read; none listed."
    )
    stations: list[NearbyStationOut] = Field(
        description=(
            "Up to three, best first (nearest first without `toward`); fewer or none where"
            " fewer fit."
        )
    )
    credit: str = Field(description="The plain source citation (OWNER-DECISIONS 301).")


@api.post(
    "/bikeshare/stations",
    response={
        200: NearbyStationsOut,
        400: ErrorOut,
        422: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        503: BusyOut,
    },
    summary="Three stations to pick up from (3/4 full) or return to (1/4 full), on your way first",
)
@decorate_view(
    ratelimit.rate_limited(ratelimit.BIKESHARE_STATIONS),
    json_body_only,
    errors_as_json,
)
def bikeshare_stations(request, body: NearbyStationsIn, response: HttpResponse):
    response["Cache-Control"] = "no-store"
    try:
        snapshot = gbfs.client.snapshot()
    except gbfs.Unavailable:
        refusal = JsonResponse(
            {
                "error": "Bikeshare station data is not available right now. Try again shortly.",
                "code": "bikeshare_unavailable",
            },
            status=503,
        )
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        refusal["Cache-Control"] = "no-store"
        return refusal
    found = bikeshare.nearby_stations(body.point, body.action, snapshot, body.toward)
    availability = "unknown" if snapshot.status is None else ("stale" if snapshot.stale else "live")
    return Status(
        200,
        {
            "action": body.action,
            "availability": availability,
            "stations": [
                {
                    "station_id": s.station_id,
                    "name": s.name,
                    "lon": s.lon,
                    "lat": s.lat,
                    "percent_full": s.percent_full,
                    "distance_m": s.distance_m,
                    "bikes": s.bikes,
                    "ebikes": s.ebikes,
                    "docks": s.docks,
                    "extra_m": s.extra_m,
                    "on_the_way": s.on_the_way,
                }
                for s in found
            ],
            "credit": gbfs.CREDIT,
        },
    )


# --- Bikeshare docks and free e-bikes on the map (v0.7.0; core.micromobility) ----------------
#
# GET /api/bikeshare/docks?bbox=west,south,east,north&operators=cabi answers the docks and
# free e-bikes in the rider's map view, from each operator's one shared live copy. The view is
# bounded and the counts capped (core.micromobility), nothing is kept, and an operator whose
# licence is not recorded is never contacted: it is listed, with `licensed` false, and nothing
# of it is shown. A GET of a map view, as a tile is: no point of the rider's is in it.


class DocksIn(Schema):
    bbox: str = Field(
        max_length=120,
        description="The map's view: west,south,east,north in degrees, at most 0.25 by 0.2.",
    )
    operators: str = Field(
        default="cabi",
        max_length=120,
        description="Comma-separated operator ids to show (cabi, the only one). Default cabi.",
    )


class DockOut(Schema):
    id: str
    name: str
    lon: float
    lat: float
    classic: int | None = Field(description="Classic bikes; null when availability is unknown.")
    ebikes: int | None = Field(description="E-bikes; null when availability is unknown.")
    docks: int | None = Field(description="Empty docks; null when availability is unknown.")
    closed: bool = Field(description="Out of service, or silent for 30 minutes.")


class FreeBikeOut(Schema):
    operator: str
    lon: float
    lat: float


class OperatorOut(Schema):
    id: str
    name: str
    initial: str
    colour: str
    licensed: bool = Field(description="False: its feed licence is not yet recorded; not shown.")
    on_by_default: bool
    docked: bool


class DocksOut(Schema):
    availability: Literal["live", "stale", "unknown", "unavailable"] = Field(
        description=(
            "`unknown`: the stations are known but not their counts; `unavailable`: the"
            " operator's feed could not be read."
        )
    )
    as_of: float | None = Field(description="When the feed was read, epoch seconds.")
    docks: list[DockOut]
    free_bikes: list[FreeBikeOut]
    operators: list[OperatorOut]
    credit: list[str] = Field(description="The plain source citations of what is shown.")


@api.get(
    "/bikeshare/docks",
    response={200: DocksOut, 400: ErrorOut, 429: ErrorOut, 500: ErrorOut},
    summary="The bikeshare docks and free e-bikes in a map view, as they are now",
)
@decorate_view(ratelimit.rate_limited(ratelimit.BIKESHARE_DOCKS), errors_as_json)
def bikeshare_docks(request, params: Query[DocksIn], response: HttpResponse):
    response["Cache-Control"] = "no-store"
    try:
        box = micromobility.parse_bbox(params.bbox)
    except ValueError as error:
        return Status(400, {"error": str(error)})
    wanted = [w.strip() for w in params.operators.split(",") if w.strip()]
    unknown = [w for w in wanted if w not in micromobility.BY_ID]
    if unknown:
        return Status(400, {"error": f"unknown operator: {', '.join(unknown)}"})
    docks: list[dict] = []
    free: list[dict] = []
    credit: list[str] = []
    availability = "unavailable"
    as_of: float | None = None
    for operator in (micromobility.BY_ID[w] for w in dict.fromkeys(wanted)):
        client = micromobility.client_for(operator)
        if client is None:
            continue
        try:
            snapshot = client.snapshot()
        except gbfs.Unavailable:
            continue
        credit.append(operator.credit)
        if operator.docked:
            docks = [dataclasses.asdict(d) for d in micromobility.docks_in(snapshot, box)]
            availability = (
                "unknown" if snapshot.status is None else ("stale" if snapshot.stale else "live")
            )
            as_of = snapshot.as_of
        free += [
            {"operator": operator.id, "lon": lon, "lat": lat}
            for lon, lat in micromobility.free_bikes_in(snapshot, box)
        ]
    return Status(
        200,
        {
            "availability": availability,
            "as_of": as_of,
            "docks": docks,
            "free_bikes": free,
            "operators": [
                {
                    "id": o.id,
                    "name": o.name,
                    "initial": o.initial,
                    "colour": o.colour,
                    "licensed": micromobility.usable(o),
                    "on_by_default": o.on_by_default,
                    "docked": o.docked,
                }
                for o in micromobility.OPERATORS
            ],
            "credit": credit,
        },
    )


# --- Short map links (v0.7.0, "Open shared locations in RouteMaker"; core.share_links) -------
#
# POST /api/share/resolve follows a short map link (maps.app.goo.gl, goo.gl/maps, maps.apple) to
# the full link it stands for, which the browser then reads for its place. A POST, so the link
# (a place the rider may be going) is in no URL or log line; it is kept nowhere.


class ShareResolveIn(Schema):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=share_links.MAX_URL, description="A short map link.")


class ShareResolveOut(Schema):
    url: str = Field(description="The full map link the short one stands for.")


@api.post(
    "/share/resolve",
    response={200: ShareResolveOut, 400: ErrorOut, 429: ErrorOut, 500: ErrorOut, 502: ErrorOut},
    summary="Follow a short map link to the full link it stands for",
)
@decorate_view(ratelimit.rate_limited(ratelimit.SHARE_RESOLVE), json_body_only, errors_as_json)
def share_resolve(request, body: ShareResolveIn, response: HttpResponse):
    response["Cache-Control"] = "no-store"
    try:
        return Status(200, {"url": share_links.resolve(body.url)})
    except share_links.NotAShortLink:
        return Status(400, {"error": "That is not a short map link RouteMaker can open."})
    except share_links.Unresolved:
        return Status(502, {"error": "That link could not be opened just now; try again shortly."})


def _stress_of(body: RouteIn) -> int:
    """The traffic slider's position a request plans at."""
    if body.stress is not None:
        return body.stress
    return presets.stress_start(body.preset, body.carrying)


def _bikeshare_body(body: RouteIn, started: float | None) -> dict:
    """A Bikeshare or Rebalance Ride plan (`core.bikeshare`): the operator's feeds, the walks
    and the ride."""
    if started is None:
        started = routing.clock()
    bike = body.bike or presets.BIKE_CLASSIC
    profile = presets.BIKESHARE_BIKES[bike]
    dials = routing.Dials(
        stress=body.stress,
        hills=profile.hills if body.hills is None else body.hills,
        when=body.when,
        closure_bypass=tuple(body.closure_bypass),
        closures_now=body.closures_now,
        blocked=_blocked(body),
        assist=profile.assist,
        avoid_gravel=body.avoid_gravel,
        # "Keep to roads, not trails" is one switch on every ride type (463b).
        trails_off=body.trails_off,
        target_distance_m=body.target_distance_m,
        system_weight_kg=body.system_weight_kg or profile.system_weight_kg,
    )
    deadline = routing.Deadline(
        started + routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S, routing.ROUTER_TIMEOUT_S
    )
    snapshot = gbfs.client.snapshot()
    services = bikeshare.RoutingServices(
        deadline,
        lambda points: routing.plan(
            points, body.preset, long_ride=False, started=started, dials=dials
        ),
    )
    return bikeshare.plan(
        body.points[0],
        body.points[1],
        bike,
        body.ending or bikeshare.ENDING_DOCK,
        snapshot,
        services,
        profile.speed_kmh,
        pickup_station=body.pickup_station,
        dropoff_station=body.dropoff_station,
        rebalance=body.preset == presets.REBALANCE,
    )


# A transit plan's candidate legs are routed only this long after the request arrived; the rest
# of the request's budget is the answer's own line (routing.plan).
TRANSIT_CANDIDATES_S = 12

# Said when the router did not draw the answer's line in time.
UNROUTED_NOTE = (
    "The router did not answer in time, so the ride's line is drawn straight and its time is"
    " estimated."
)


def _unrouted_line(
    points: list[list[float]],
    preset_name: str,
    dials,
    seconds: float,
    metres: float | None = None,
) -> dict:
    """The answer's line when the router did not draw it: straight from end to end, its time
    the plan's own estimate, its streets unknown. Everything else in the body is empty. Also
    walking the whole way, the line as the pedestrian router walked it (`metres` its length)."""
    if metres is None:
        straight_m = sum(
            haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False)
        )
        metres = straight_m * transit.DETOUR
    metres = round(metres, 1)
    preset = presets.PRESETS[preset_name]
    stress = presets.stress_start(preset_name, None) if dials.stress is None else dials.stress
    return {
        "preset": preset.name,
        "variant": preset.variant,
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in points],
        },
        "distance_m": metres,
        "duration_s": round(seconds, 1),
        "climb_m": 0.0,
        "descent_m": 0.0,
        "stress_m": {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0, "5": 0.0, "unknown": metres},
        "facility_m": {"path": 0.0, "protected": 0.0, "lane": 0.0, "none": 0.0, "unknown": metres},
        "stress_adjustments": [],
        "stress_spans": [],
        "dials": {
            "stress": stress,
            "hills": preset.hills if dials.hills is None else dials.hills,
            "when": dials.when or routing.default_when(),
            "carrying": None,
            "assist": False,
        },
        "hills_seek": None,
        "hills_avoid": None,
        "attribution": [],
        "leg_ends": [len(points) - 1],
        "intersections": None,
        "calm_search": None,
        "detour": None,
    }


def _walked_line(plan: transit.Plan, preset_name: str, dials, services=None) -> dict:
    """The answer's line is a walk (walking the whole way, or a trip whose line is a walk): the
    walk itself, as the pedestrian router walked it (or straight where it did not), timed at
    walking pace; no bike route is asked. `services` walks a leg not yet walked by the router."""
    leg = plan.legs[plan.ride]
    points = [list(p) for p in leg.coordinates]
    metres = None
    walked = services.walk(points[0], points[-1]) if services is not None else None
    if walked is not None and len(walked.coordinates) >= 2:
        points = [list(p) for p in walked.coordinates]
        metres = walked.metres
    elif not leg.estimated:
        metres = sum(
            haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False)
        )
    return _unrouted_line(points, preset_name, dials, leg.seconds, metres)


def _transit_body(body: RouteIn, started: float | None) -> dict:
    """A transit ride type (`core.transit`): the options, the chosen one's first ride routed."""
    if started is None:
        started = routing.clock()
    when = body.depart_at or timezone.now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=ridetime.ZONE)
    schedule = transit.load(settings.TRANSIT_SCHEDULE_PATH, when.astimezone(ridetime.ZONE).date())
    # The docks first, and the candidates' clock after them (TB-8): a slow feed read must not
    # spend the candidates' budget. Feeds that cannot be read are no docks, with a note, not a
    # refusal (TB-2): the trip walks at both ends.
    share_snapshot = share_note = None
    if body.preset == presets.BIKESHARE_TRANSIT:
        try:
            share_snapshot = gbfs.client.snapshot()
        except gbfs.Unavailable as error:
            logger.warning("bikeshare feeds unavailable for a transit plan: %s", error)
            share_snapshot = gbfs.Snapshot(fetched_at=0.0, stations=[], status={})
            share_note = "Bikeshare docks can't be read right now: walking at both ends."
    candidates_until = min(
        routing.clock() + TRANSIT_CANDIDATES_S,
        started + routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S,
    )
    # The candidates' calls stop `TRANSIT_CANDIDATES_S` in, leaving the answer's own line
    # (routing.plan, below) the rest of the request's budget: a slow router estimates candidates,
    # it never times out the plan.
    # Novice and Nervous's transit options (v0.7.0): the bike legs priced as that ride type
    # prices roads, one level up; a share bike keeps its own pace.
    leg_preset = presets.NOVICE if body.novice_legs else body.preset
    leg_costing = None
    if body.novice_legs and body.preset == presets.BIKESHARE_TRANSIT:
        leg_costing = presets.costing(presets.NOVICE)
        leg_costing["bicycle"]["cycling_speed"] = presets.BIKESHARE_CLASSIC_SPEED_KMH
    candidate_costing = leg_costing
    if candidate_costing is None:
        # The candidates priced at the rider's own traffic and hills sliders, as the answer's
        # line is (routing.plan): candidates timed at the ride type's own settings ranked one
        # trip quickest that came out slower once its line was routed at the rider's.
        stress = body.stress
        if stress is None:
            stress = presets.stress_start(leg_preset, body.carrying)
        candidate_costing = presets.costing(leg_preset, stress, body.hills)
    services = transit.RoutingServices(
        candidates_until,
        leg_preset,
        costing=candidate_costing,
        when=body.when or routing.default_when(),
    )
    start, end = body.points
    # WMATA's live reading (core.wmata_live), if any: read before the search, which ranks a
    # station with no working elevator on the way 15 min down, and used after it (below).
    live = wmata_live.client.snapshot()
    if body.preset == presets.BIKESHARE_TRANSIT:
        found = transit.plan_bikeshare(
            schedule, start, end, when, services, share_snapshot, hop=body.novice_hop
        )
        if share_note is not None:
            found.notes.insert(0, share_note)
    else:
        options = presets.costing(body.preset)["bicycle"]
        speed = options.get(
            "cycling_speed",
            presets.VALHALLA_DEFAULT_SPEED_KMH[options.get("bicycle_type", "Hybrid")],
        )
        # A station whose elevators are all out is ranked 15 min down for the bike, so the
        # next one over usually wins (Stephen, 2026-10-21).
        blocked = transit_live.blocked_stations(live)
        bike_schedule = transit.with_elevators_out(
            schedule,
            [(station.lon, station.lat) for station in blocked],
        )
        found = transit.plan_bike(
            bike_schedule, start, end, when, services, speed, hop=body.novice_hop
        )
    searched = routing.clock()
    dials = routing.Dials(
        stress=body.stress,
        hills=body.hills,
        when=body.when,
        closure_bypass=tuple(body.closure_bypass),
        closures_now=body.closures_now,
        blocked=_blocked(body),
        avoid_gravel=body.avoid_gravel,
        trails_off=body.trails_off,
        system_weight_kg=body.system_weight_kg,
        # The lines are priced as the candidates were (`leg_costing`): a share bike priced as
        # Novice keeps the share bike's pace, so the trip is timed again (retime) at it.
        cycling_speed_kmh=(
            leg_costing["bicycle"]["cycling_speed"] if leg_costing is not None else None
        ),
        # A trip's lines say no walks past busy stretches (`core.novice_walks`): the trip is
        # how Novice and Nervous gets past them here.
        novice_walks=False,
    )
    # WMATA's live reading (core.wmata_live), if any: a trip through a closed station is left out,
    # and the block says the live values (core.transit_live).
    # A plan for now takes its Metro steps' departures from WMATA's next trains, where they
    # cover them, before it is ranked.
    found = transit_live.with_live_trains(found, live)
    found = transit_live.skip_closed(found, live)
    # Novice and Nervous's hop past the busy stretch (v0.11.0): planned where there is one,
    # unless the rider chose another option.
    found = transit.choose(found, body.transit_option, schedule, hop=body.novice_hop is not None)
    # The chosen trip's Metrobus steps' next buses (core.wmata_bus, v0.9.0), asked now, beside
    # the routing, so the answer waits for them little if at all.
    bus_ask = _ask_buses(found)
    # The trip's other walks and rides are routed for the map in what is left of the budget.
    draw = transit.RoutingServices(
        min(
            started + routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S,
            routing.clock() + transit.DRAW_BUDGET_S,
        ),
        leg_preset,
        max_calls=transit.MAX_DRAW_CALLS,
        per_call_s=transit.DRAW_CALL_S,
        costing=leg_costing,
    )

    def answered(answer: dict, plan: transit.Plan, lines: dict[int, dict] | None = None) -> dict:
        # The later rides routed for their stress colours (`lines`) are drawn as routed; the
        # trip's other walks and rides are routed for the map (transit.drawn).
        lines = lines or {}
        buses = _buses_for(plan, bus_ask)
        plan = transit_live.with_live_buses(plan, buses)
        block = _transit_block(transit.drawn(plan, draw, skip=lines), schedule, live, buses)
        answer["transit"] = _with_leg_lines(block, lines)
        return answer

    if found.option.walk:
        return answered(_walked_line(found, body.preset, dials), found)
    leg = found.legs[found.ride]
    # The line is the chosen option's first ride (or walk). Riding directly there, or an option
    # whose every ride and walk is a few yards (nothing the router could route), is drawn start to
    # end instead, and the plan keeps its own times.
    whole = (found.option.direct and body.preset == presets.BIKE_TRANSIT) or (
        transit.line_m(leg) < transit.MIN_LINE_M
    )
    retime = not whole or found.option.direct
    if not whole and leg.mode in (transit.WALK, transit.TAKE):
        # The line is a walk (Bikeshare + 🚶🚆🚌 with no ride worth a line): walked by the
        # pedestrian router, never the bike's, and the plan keeps its walking times.
        return answered(_walked_line(found, body.preset, dials, draw), found)
    if whole:
        ride_from, ride_to = list(start), list(end)
    else:
        ride_from = list(leg.coordinates[0])
        ride_to = list(leg.coordinates[-1])

    def line(points: list[list[float]]) -> dict | None:
        """The answer's line routed, or None when the router did not answer in time."""
        try:
            answered = routing.plan(
                points, leg_preset, long_ride=False, started=started, dials=dials
            )
            # The ride type asked for, whichever ride type priced its bike leg.
            answered["preset"] = body.preset
            answered["novice"] = None
            return answered
        except (routing.RouterUnavailable, routing.DeadlineExceeded) as error:
            logger.warning("transit plan: the answer's line was not routed: %s", error)
            return None

    def unrouted(points: list[list[float]], plan: transit.Plan) -> tuple[dict, transit.Plan]:
        # As a short leg is: drawn straight, the plan keeping its own (estimated) times.
        drawn = _unrouted_line(points, body.preset, dials, plan.legs[plan.ride].seconds)
        return drawn, dataclasses.replace(plan, notes=[*plan.notes, UNROUTED_NOTE])

    # Every later ride of the chosen option (the ride from the exit station to the destination,
    # the far end's bikeshare ride) is routed as the first is, with the same ride type and dials,
    # for its stress colours (the owner, v0.7.0: "it doesn't seem to include the LTS of the
    # section towards the destination"). They run beside the answer's own line on the router
    # pool (`core.parallel`, so a request never has more than its bound of router calls in
    # flight beside its own thread), inside the same budget; one that fails or runs out of time
    # keeps its plain line from the search, and the plan never fails for it.
    asked: list = []
    try:
        later = {} if whole else _later_rides(found, leg_preset, started, dials)
        asked.append(later)
        answer = line([ride_from, ride_to])
        lines = _collected(later, started)
        if answer is None:
            answer, found = unrouted([ride_from, ride_to], found)
            retime = False
        # Each routed ride's own time (the later rides' too); the waits for infrequent
        # departures are worked out again from them (transit.with_rides).
        routed = {index: float(a["duration_s"]) for index, a in lines.items()}
        if retime:
            routed[found.ride] = float(answer["duration_s"])
        # Their busy metres too, from the answers' own stress breakdowns, as the options say.
        busy = {index: _busy_m(a) for index, a in lines.items()}
        if retime:
            busy[found.ride] = _busy_m(answer)
        busy = {index: m for index, m in busy.items() if m is not None}
        # The rider's own pick stays chosen; otherwise the best once routed is (Stephen,
        # 2026-10-21: a trip that came out at 34 min stayed chosen above riding at 31). Novice
        # and Nervous's hop, chosen because the rider asked to skip the busy stretch, stays too.
        keep = (body.transit_option is not None and found.asked is None) or found.option.hop
        timed = transit.with_rides(found, routed, busy, keep=keep) if routed else found
        if timed.option.key != found.option.key:
            # The chosen trip's departure cannot be caught after all and it was left out, or
            # as routed it is no longer the best: the best left is planned, its own line routed
            # (or drawn start to end), and its later rides routed for their colours. Their
            # times stay the plan's own: timing them again could drop this option too.
            leg = timed.legs[timed.ride]
            if timed.option.walk:
                return answered(_walked_line(timed, body.preset, dials), timed)
            walked = leg.mode in (transit.WALK, transit.TAKE) and not timed.option.direct
            if walked and transit.line_m(leg) >= transit.MIN_LINE_M:
                return answered(_walked_line(timed, body.preset, dials, draw), timed)
            again_whole = timed.option.direct and body.preset == presets.BIKE_TRANSIT
            if again_whole:
                points = [list(start), list(end)]
            elif transit.line_m(leg) >= transit.MIN_LINE_M:
                points = [list(leg.coordinates[0]), list(leg.coordinates[-1])]
            else:
                again_whole = True
                points = [list(start), list(end)]
            later = {} if again_whole else _later_rides(timed, leg_preset, started, dials)
            asked.append(later)
            answer = line(points)
            lines = _collected(later, started)
            if answer is None:
                answer, timed = unrouted(points, timed)
        found = timed
    finally:
        # A later ride not started yet is not asked; one still running past its wait is left
        # to its own deadline, not waited for.
        for later in asked:
            for pending in later.values():
                if isinstance(pending, Future):
                    pending.cancel()
    answered(answer, found, lines)
    logger.info(
        "transit plan %s: search %.1f s (candidates %.1f s, %d calls), line %.1f s",
        body.preset,
        searched - started - services.spent_s,
        services.spent_s,
        services.calls,
        routing.clock() - searched,
    )
    return answer


def _busy_m(answered: dict) -> float | None:
    """A routed answer's metres on busy roads (LTS 3 and up), or None without its breakdown."""
    stress = answered.get("stress_m")
    if not stress:
        return None
    return float(sum(stress.get(key, 0.0) for key in ("3", "4", "5")))


def _later_rides(
    plan: transit.Plan,
    leg_preset: str,
    started: float,
    dials: routing.Dials,
) -> dict[int, Future | Callable[[], dict | None]]:
    """Each ride of the chosen option after its route line (own bike or share bike, long
    enough to route): the same ride type, dials and budget, by the leg's index in the option.
    Sent to the router pool (`core.parallel`) to run beside the route line; where the pool is
    off (ROUTER_PARALLEL_CALLS=1), kept to run in turn after the line (`_collected`), so the
    line is never kept waiting behind them."""
    option = plan.option
    later: dict[int, Future | Callable[[], dict | None]] = {}
    for index, leg in enumerate(option.legs):
        if index == option.ride or leg.mode not in (transit.RIDE, transit.SHARE):
            continue
        if transit.line_m(leg) < transit.MIN_LINE_M:
            continue
        points = [list(leg.coordinates[0]), list(leg.coordinates[-1])]
        if parallel.enabled():
            later[index] = parallel.submit(_leg_line, points, leg_preset, started, dials)
        else:
            later[index] = partial(_leg_line, points, leg_preset, started, dials)
    return later


def _leg_line(points: list[list[float]], leg_preset: str, started: float, dials) -> dict | None:
    """A later ride's line routed for its stress colours, or None: whatever goes wrong, the
    leg keeps the plain line it was found with. Without the request's timing recorder: a
    plan restarts its recorder's phases, which are the answer's own line's."""
    token = timing.start(None)
    on_pool = parallel.inside()
    try:
        return routing.plan(points, leg_preset, long_ride=False, started=started, dials=dials)
    except Exception as error:  # a later leg never fails the plan
        logger.warning("transit plan: a later ride's line was not routed: %s", error)
        return None
    finally:
        timing.stop(token)
        if on_pool:
            # The pool thread's own database connection (the plan reads the approved
            # junctions and the stress join): closed, as a pool thread is not the request's.
            connections.close_all()


def _collected(later: dict, started: float) -> dict[int, dict]:
    """The later rides that were routed in time, by leg index. A call still running when the
    request's router budget ends is let go: its leg keeps its plain line. One kept to run in
    turn (the pool off) runs here, after the line, while the budget lasts."""
    out: dict[int, dict] = {}
    end = started + routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S
    for index, pending in later.items():
        if not isinstance(pending, Future):
            answered = pending() if routing.clock() < end else None
        else:
            try:
                answered = pending.result(timeout=max(0.0, end - routing.clock()))
            except FutureTimeout:
                logger.warning("transit plan: a later ride's line ran out of time")
                continue
        if answered is not None:
            out[index] = answered
    return out


def _with_leg_lines(block: dict, lines: dict[int, dict]) -> dict:
    """The `transit` block with each routed later ride's step drawn as routed, with its stress
    sections in the form the route's own line has them (`stress_spans`), for the map, its
    legend and the words to colour and say alike."""
    steps = block["steps"]
    for index, answered in lines.items():
        if index >= len(steps) or steps[index]["route_line"]:
            continue
        coordinates = answered.get("geometry", {}).get("coordinates") or []
        spans = answered.get("stress_spans")
        if len(coordinates) < 2 or not spans:
            continue
        steps[index]["coordinates"] = coordinates
        steps[index]["stress_spans"] = spans
        # Its length, climb and elevation, so the trip's totals and chart cover every ride, not
        # the first alone (Stephen, 2026-10-21: "The elevation and climbs are only shown for
        # the first stretch in a multi-modal trip").
        for field in ("distance_m", "climb_m", "descent_m", "profile"):
            if answered.get(field) is not None:
                steps[index][field] = answered[field]
    return block


def _transit_block(plan: transit.Plan, schedule, live, buses=None) -> dict:
    """The answer's `transit` block, with WMATA's live values where there are any."""
    return transit_live.annotate(transit.block(plan, schedule), plan, live, buses)


# Two threads for the plans' bus questions (core.wmata_bus.lives, which asks its stops at once).
_BUS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wmata-bus")


def _ask_buses(plan: transit.Plan) -> tuple[str, Future] | None:
    """The chosen trip's live bus lines, asked in the background; None with nothing to ask."""
    legs = transit_live.bus_legs(plan)
    if not legs or not wmata_live.configured():
        return None
    return plan.option.key, _BUS_POOL.submit(wmata_bus.client.lives, legs)


def _buses_for(plan: transit.Plan, asked) -> wmata_bus.StepLives | None:
    """The live bus lines for the trip answered: the ones asked, if it is still the trip asked
    about (else asked again), within `wmata_bus.PLAN_BUDGET_S`."""
    if asked is not None and asked[0] == plan.option.key:
        try:
            return asked[1].result(timeout=wmata_bus.PLAN_BUDGET_S)
        except Exception:  # noqa: BLE001 - a bus line is never worth a plan
            return None
    legs = transit_live.bus_legs(plan)
    if not legs or not wmata_live.configured():
        return None
    return wmata_bus.client.lives(legs)


def _transit_refusal(message: str, code: str, status: int):
    refusal = JsonResponse({"error": message, "code": code}, status=status)
    if status == 503:
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
    return refusal


# --- Stations closed for the day (the owner, 2026-10-12) ----------------------------------
#
# GET /api/transit/closures lists the rail stations with no service at all on a service day (a
# weekend or holiday a line does not run, or a closure published in the timetable), for the
# map to strike through and grey. A station outside its hours on a day it runs is not listed.


class ClosuresIn(Schema):
    at: datetime | None = Field(
        default=None,
        description=(
            "When, ISO 8601 (local time in Washington without an offset), within a year of"
            " now. Absent: now."
        ),
    )

    @field_validator("at")
    @classmethod
    def _at_near_now(cls, value: datetime | None) -> datetime | None:
        return near_now(value)


class ClosedStationOut(Schema):
    name: str
    system: str = Field(description='The system, by name: "Metro", "MARC".')
    lon: float
    lat: float
    reason: str = Field(description='"no MARC weekend service"')


class StationAlertOut(Schema):
    name: str
    lon: float
    lat: float
    alert: bool = Field(description="A WMATA incident names this station.")
    elevator_out: bool = Field(description="WMATA lists an elevator out here.")


class ClosuresOut(Schema):
    service_day: str = Field(description="The GTFS service day (before 3 am, the day before).")
    stations: list[ClosedStationOut]
    alerts: list[StationAlertOut] = Field(
        default_factory=list,
        description="Asked for now only: open Metro stations with a WMATA alert or elevator out.",
    )


@api.get(
    "/transit/closures",
    response={200: ClosuresOut, 400: ErrorOut, 429: ErrorOut, 500: ErrorOut, 503: BusyOut},
    summary="The rail stations with no service at all on a day, to grey on the map",
)
@decorate_view(ratelimit.rate_limited(ratelimit.COVERAGE), errors_as_json)
def transit_closures(request, params: Query[ClosuresIn], response: HttpResponse):
    when = params.at or timezone.now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=ridetime.ZONE)
    try:
        schedule = transit.load(
            settings.TRANSIT_SCHEDULE_PATH, when.astimezone(ridetime.ZONE).date()
        )
    except transit.Unavailable:
        return _transit_refusal(
            "Transit times are not available on this server right now.", "transit_unavailable", 503
        )
    moment = transit.moment_of(when)
    stations = [
        {
            "name": c.stop.name,
            "system": c.system.name,
            "lon": c.stop.point[0],
            "lat": c.stop.point[1],
            "reason": c.reason,
        }
        for c in transit.closed_stations(schedule, moment)
    ]
    # Asked for now (no `at`): the Metro stations WMATA's incidents say are closed (the owner,
    # 2026-10-18), struck through on the map as a timetable closure is. Short-lived, so cached
    # for a minute, not five.
    live = wmata_live.client.snapshot() if params.at is None else None
    named = {s["name"] for s in stations}
    seen: set[str] = set()
    for code in live.closed() if live is not None else {}:
        station = live.stations.get(code)
        if station is None or station.name in named or station.name in seen:
            continue
        seen.add(station.name)
        stations.append(
            {
                "name": station.name,
                "system": transit_live.METRO,
                "lon": station.lon,
                "lat": station.lat,
                "reason": "WMATA service alert",
            }
        )
    response["Cache-Control"] = f"public, max-age={60 if live is not None else 300}"
    return {
        "service_day": moment.service_day.isoformat(),
        "stations": stations,
        "alerts": _station_alerts(live, {s["name"] for s in stations}),
    }


def _station_alerts(live, closed_names: set[str]) -> list[dict]:
    """The Metro stations a WMATA incident names, and those with an elevator out, for their
    small badges on the map (the owner, 2026-10-18: "Put a little notice marker on all the
    stations that have alerts", "For elevator out, use an X'd out elevator icon"). A closed
    station is struck through instead; a line-wide incident badges no station."""
    if live is None:
        return []
    named = live.named()
    lifts = live.elevator_out_codes()
    out: dict[str, dict] = {}
    for code in sorted(named | lifts):
        station = live.stations.get(code)
        if station is None or station.name in closed_names:
            continue
        item = out.setdefault(
            station.name,
            {
                "name": station.name,
                "lon": station.lon,
                "lat": station.lat,
                "alert": False,
                "elevator_out": False,
            },
        )
        item["alert"] = item["alert"] or code in named
        item["elevator_out"] = item["elevator_out"] or code in lifts
    return list(out.values())


# --- A station's times, for its card (the owner, 2026-10-12) -------------------------------
#
# GET /api/transit/station-times: the lines at a map station now (or `at`), from the installed
# schedule (Metro on its typical timetable where no WMATA GTFS is): a frequent line's minutes
# between trains, and a commuter line's next train each way (core.transit.station_times). Small,
# and cached by the browser for a minute. 503 where no schedule can be read: the card just says
# no times.


class StationTimesIn(Schema):
    lon: float = Field(ge=-180, le=180, description="The map station's point.")
    lat: float = Field(ge=-90, le=90)
    at: datetime | None = Field(
        default=None,
        description=(
            "When, ISO 8601 (local time in Washington without an offset), within a year of"
            " now. Absent: now."
        ),
    )

    @field_validator("at")
    @classmethod
    def _at_near_now(cls, value: datetime | None) -> datetime | None:
        return near_now(value)


class LineTimeOut(Schema):
    system: str = Field(description='The system, by name: "Metro", "MARC", "VRE".')
    line: str = Field(description='"Red Line", "Penn Line".')
    station: str = Field(description="The stop's name in the timetable.")
    kind: Literal["every", "next", "none"] = Field(
        description=(
            "`every`: a frequent line, `every_min` minutes between trains. `next`: the next train"
            " toward `toward`, at `time`. `none`: no more trains today toward `toward` (none at"
            " all today when `today` is false; `toward` null for both ways)."
        )
    )
    every_min: int | None = None
    toward: str | None = Field(default=None, description="The train's last stop.")
    time: str | None = Field(default=None, description='Local clock time: "5:42 pm".')
    at: datetime | None = Field(default=None, description="The departure, with its offset.")
    today: bool = True


class LiveTrainOut(Schema):
    line: str = Field(description='"Red Line".')
    toward: str = Field(description="The train's last stop.")
    minutes: list[int] = Field(description="Minutes until the next trains that way (0: arriving).")
    when: str = Field(description='"3 min, 11 min"; "arriving", "boarding".')


class LiveElevatorOut(Schema):
    words: str = Field(
        description='"Elevator out at Gallery Place: carry your bike on the stairs."'
    )
    where: str = Field(description="WMATA's description of the unit.")


class StationLiveOut(Schema):
    station: str
    trains: list[LiveTrainOut]
    elevators: list[LiveElevatorOut]
    alerts: list[str] = Field(description="WMATA's rail incidents on the station's lines.")
    credit: str = Field(description='"Data: WMATA".')
    as_of: str = Field(description="When WMATA was read, local ISO time.")


class StationTimesOut(Schema):
    service_day: str = Field(description="The GTFS service day (before 3 am, the day before).")
    source: Literal["scheduled"] = Field(description="Where `lines` are from: the timetable.")
    lines: list[LineTimeOut]
    live: StationLiveOut | None = Field(
        default=None,
        description="A Metro station's live values (core.transit_live.station); null where none.",
    )


@api.get(
    "/transit/station-times",
    response={200: StationTimesOut, 400: ErrorOut, 429: ErrorOut, 500: ErrorOut, 503: BusyOut},
    summary="A rail station's lines now: minutes between trains, or the next train each way",
)
@decorate_view(ratelimit.rate_limited(ratelimit.STATION_TIMES), errors_as_json)
def transit_station_times(request, params: Query[StationTimesIn], response: HttpResponse):
    when = params.at or timezone.now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=ridetime.ZONE)
    try:
        schedule = transit.load(
            settings.TRANSIT_SCHEDULE_PATH, when.astimezone(ridetime.ZONE).date()
        )
    except transit.Unavailable:
        return _transit_refusal(
            "Transit times are not available on this server right now.", "transit_unavailable", 503
        )
    moment = transit.moment_of(when)
    found = transit.station_times(schedule, (params.lon, params.lat), when)
    # Live values only for now: a time asked for (`at`) is the timetable's alone.
    live = (
        None
        if params.at
        else transit_live.station((params.lon, params.lat), wmata_live.client.snapshot())
    )
    response["Cache-Control"] = "public, max-age=30" if live else "public, max-age=60"
    return {
        "service_day": moment.service_day.isoformat(),
        "source": transit.SCHEDULED,
        "lines": [_line_time(t, moment.service_day) for t in found],
        "live": live,
    }


class NextVehicleIn(Schema):
    system: Literal["Metro", "Metrobus"] = Field(description="The step's system.")
    line: str = Field(
        min_length=1, max_length=40, description='The step\'s line: "Red Line"; a route: "52".'
    )
    lon: float = Field(ge=-180, le=180, description="The boarding station or stop's point.")
    lat: float = Field(ge=-90, le=90)
    to_lon: float = Field(ge=-180, le=180, description="The step's last stop: its way.")
    to_lat: float = Field(ge=-90, le=90)


class NextVehicleOut(Schema):
    kind: Literal["train", "bus"]
    text: str = Field(
        description=(
            '"Next Red Line train is at Dupont Circle, 2 stations away."; "Bus 52 is 0.8 mi'
            ' away (1.3 km), 3 stops back."'
        )
    )
    label: str = Field(description="The map mark's name, for a screen reader.")
    point: list[float] = Field(description="[lon, lat] for the map's mark.")
    away: int | None = Field(
        description="Stations (or stops) before the rider's, for saying it again on a change."
    )
    credit: str = Field(description='"Data: WMATA".')
    source: Literal["live"] = "live"
    as_of: str = Field(description="When WMATA was read, local ISO time.")


class NextVehicleAnswer(Schema):
    vehicle: NextVehicleOut | None = Field(
        description="Where the next one the step's way is; null with no reading or none coming."
    )


@api.get(
    "/transit/next-vehicle",
    response={200: NextVehicleAnswer, 400: ErrorOut, 429: ErrorOut, 500: ErrorOut},
    summary="Where the next Metro train or Metrobus is, for a rider waiting to board it",
)
@decorate_view(ratelimit.rate_limited(ratelimit.NEXT_VEHICLE), errors_as_json)
def transit_next_vehicle(request, params: Query[NextVehicleIn], response: HttpResponse):
    """Asked about every 25 s by the page while its rider waits at a boarding (Ride mode, at the
    end of the ride to it), and never otherwise. With no WMATA key, WMATA not answering, or
    nothing matched, `vehicle` is null and the page shows nothing (core.wmata_trains,
    core.wmata_bus)."""
    board, alight = (params.lon, params.lat), (params.to_lon, params.to_lat)
    response["Cache-Control"] = "private, max-age=15"
    if not wmata_live.configured():
        return {"vehicle": None}
    if params.system == "Metro":
        found = transit_live.train_where(
            wmata_live.client.snapshot(), board, alight, params.line, wmata_trains.client.snapshot()
        )
        return {"vehicle": transit_live.vehicle_out("train", found)}
    try:
        today = timezone.now().astimezone(ridetime.ZONE).date()
        schedule = transit.load(settings.TRANSIT_SCHEDULE_PATH, today)
    except transit.Unavailable:
        schedule = None
    back = transit_live.bus_stops_back(schedule, params.line, board, alight)
    found = wmata_bus.client.where(params.line, board, alight, back)
    return {"vehicle": transit_live.vehicle_out("bus", found)}


def _line_time(t: transit.LineTime, service_day) -> dict:
    # After midnight, a way's next train may be the new day's first: its own service day.
    service_day = t.service_day or service_day
    at = None
    if t.depart is not None:
        at = transit.day_zero(service_day) + timedelta(minutes=round(t.depart))
    return {
        "system": t.system.name,
        "line": t.route,
        "station": t.stop.name,
        "kind": t.kind,
        "every_min": t.every_min,
        "toward": t.toward,
        "time": None if t.depart is None else transit.clock(t.depart, service_day),
        "at": None if at is None else at.astimezone(ridetime.ZONE).isoformat(),
        "today": t.today,
    }


def _plan(request, body: RouteIn, response: HttpResponse, long_ride: bool, long_calm: bool = False):
    started = getattr(request, "routing_started", None)
    if body.preset in presets.TRANSIT_PRESETS:
        try:
            return Status(200, _transit_body(body, started))
        except transit.NoTransit as refusal:
            return _transit_refusal(str(refusal), "no_transit", 422)
        except transit.Unavailable as error:
            logger.warning("transit plan refused: %s", error)
            return _transit_refusal(
                "Transit times are not available on this server right now.",
                "transit_unavailable",
                503,
            )
        except gbfs.Unavailable:
            return _transit_refusal(
                "Bikeshare station data is not available right now, so no dock can be chosen."
                " Try again shortly.",
                "transit_unavailable",
                503,
            )
        except (
            routing.TooLong,
            routing.NoRoute,
            routing.RouterUnavailable,
            routing.DeadlineExceeded,
        ) as error:
            return _router_refusal(error, body)
    if body.preset in presets.BIKESHARE_PRESETS:
        try:
            return Status(200, _bikeshare_body(body, started))
        except bikeshare.NoBikeshare as refusal:
            return JsonResponse({"error": str(refusal), "code": "no_bikeshare"}, status=422)
        except gbfs.Unavailable:
            refusal = JsonResponse(
                {
                    "error": (
                        "Bikeshare station data is not available right now, so no dock can be "
                        "chosen. Try again shortly."
                    ),
                    "code": "bikeshare_unavailable",
                },
                status=503,
            )
            refusal["Retry-After"] = str(DEADLINE_RETRY_S)
            return refusal
        except (
            routing.TooLong,
            routing.NoRoute,
            routing.RouterUnavailable,
            routing.DeadlineExceeded,
        ) as error:
            return _router_refusal(error, body)
    try:
        return Status(200, _planned(body, _bike_dials(body), started, long_ride, long_calm))
    except (
        routing.TooLong,
        routing.NoRoute,
        routing.RouterUnavailable,
        routing.DeadlineExceeded,
    ) as error:
        return _router_refusal(error, body, long_ride or long_calm)


def _blocked(body: RouteIn) -> tuple[tuple[tuple[float, float], ...], ...]:
    """The roads the rider marked closed on this ride (`blocked_lines`), as the dials hold them."""
    return tuple(tuple((p[0], p[1]) for p in line) for line in body.blocked_lines)


def _bike_dials(body: RouteIn) -> routing.Dials:
    """The dials of a bike-only plan (not Bikeshare's nor a transit trip's), as asked."""
    return routing.Dials(
        stress=body.stress,
        hills=body.hills,
        when=body.when,
        closure_bypass=tuple(body.closure_bypass),
        closures_now=body.closures_now,
        blocked=_blocked(body),
        carrying=body.carrying,
        assist=body.assist,
        avoid_gravel=body.avoid_gravel,
        trails_off=body.trails_off,
        target_distance_m=body.target_distance_m,
        system_weight_kg=body.system_weight_kg,
        loop=body.loop,
        debug_junctions=body.debug_junctions,
        mtb_level=body.mtb_level,
        mtb_preferred=body.mtb_preferred,
        vias=tuple(body.via_points),
        follow=_follow_line(body),
        follow_exact=body.follow_exact,
        straight=tuple(body.straight_legs),
        heading=body.heading,
        ride_replan=body.ride_replan,
        dirt_ridden=body.ride_replan and body.dirt_ridden,
        ahead_only=body.ahead_only,
        dirt_closed=body.ride_replan and body.dirt_closed,
    )


def _follow_line(body: RouteIn) -> tuple[tuple[float, float], ...] | None:
    """The request's line to follow (`RouteIn.follow`), or None where it has none or the
    line is not one a route can follow; the plan is then made through its points."""
    if not body.follow:
        return None
    try:
        return tuple(follow.checked_line(body.follow, settings.COVERAGE_BBOX))
    except follow.LineProblem as problem:
        logger.info("a line to follow was not followed: %s", problem)
        return None


def _planned(body: RouteIn, dials, started: float | None, long_ride: bool, long_calm: bool) -> dict:
    """The plan's answer, from the short-term cache where an identical request was
    answered within its life (`core.route_cache`, v0.7.0 "Faster routing" step 5), else
    planned and kept there where it may be."""
    timings = timing.current()
    when = body.when or routing.default_when()
    key = route_cache.key_for(
        body.model_dump(mode="json"),
        when,
        routing.planning_time(when=when),
        "long_ride" if long_ride else "long_calm" if long_calm else "",
    )
    if timings is not None:
        timings.mark("cache")
    if key is not None:
        kept = route_cache.get(key.key, quick=body.quick)
        if kept is not None:
            if timings is not None:
                timings.note("cache", "hit")
            return kept
    if timings is not None:
        timings.note("cache", "miss" if key is not None else "off")
    failures_before = timings.failures if timings is not None else 0
    try:
        answered = routing.plan_onward(
            body.points,
            body.preset,
            long_ride=long_ride,
            started=started,
            dials=dials,
            quick=body.quick,
            candidates=body.candidates,
        )
    except (routing.NoRoute, routing.TooLong):
        if dials.follow is None:
            raise
        # The line matched no way on this ride type: planned through its points instead,
        # and the answer says it does not follow the file (`follows_file`).
        logger.info(
            "a followed line matched no way on %s; planning through its points", body.preset
        )
        dials = dataclasses.replace(dials, follow=None)
        answered = routing.plan_onward(
            body.points,
            body.preset,
            long_ride=long_ride,
            started=started,
            dials=dials,
            quick=body.quick,
            candidates=body.candidates,
        )
    if key is not None:
        preset = presets.PRESETS[body.preset]
        own_variant = presets.variant_for_ride(
            body.preset,
            when,
            bool(body.assist) and preset.assist_speed_kmh is not None,
            bool(body.trails_off),
        )
        if own_variant in routing.TWIN_VARIANTS and not routing._is_promoted(own_variant):
            # Planned on the standard graph by design where no weekend or off-road build is
            # served; an answer from it while the twin is merely down is not kept.
            own_variant = "standard"
        failures = (timings.failures if timings is not None else 0) - failures_before
        # An answer whose plan ran into the answer's reserve may have skipped work for time.
        budget_s = routing.LONG_PLAN_BUDGET_S if long_ride or long_calm else routing.PLAN_BUDGET_S
        late = started is not None and routing.clock() - started >= (
            budget_s - routing.ANSWER_RESERVE_S
        )
        if not late and route_cache.keepable(answered, own_variant, failures):
            route_cache.put(key.key, answered, key.valid_s)
    return answered


def _router_refusal(error: Exception, body: RouteIn, long_plan: bool = False):
    """The answer for a router error, the same for every ride type."""
    if isinstance(error, routing.TooLong):
        return Status(400, {"error": ROUTER_TOO_LONG})
    if isinstance(error, routing.NoRoute):
        message = "No route joins these points on this preset."
        if error.no_path and presets.PRESETS[body.preset].variant == "no-trail":
            # PLAN, Routing model: a no-route result on the no-trail variant
            # reports the disconnection rather than failing blankly.
            message += (
                " A Mass Ride routes only on roadways, and removing trails can leave"
                " no roadway-legal connection between two points."
            )
        elif error.no_path and body.trails_off:
            # The same for a ride with "Keep to roads, not trails" on, in its words.
            message += (
                ' With "Keep to roads, not trails" on, this ride uses only roadways, and'
                " there may be no roadway-legal connection between two points."
            )
        return Status(422, {"error": message})
    if isinstance(error, routing.RouterUnavailable):
        return Status(502, {"error": "The router is not answering; try again shortly."})
    # A JsonResponse rather than Status, so an ordinary 503 stays exactly
    # {"error"} instead of carrying "code": null.
    if long_plan:
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
        trails_off=body.trails_off,
        mtb_level=body.mtb_level,
        mtb_preferred=body.mtb_preferred,
        loop=body.loop,
    )
    started = getattr(request, "routing_started", None)
    try:
        return Status(200, stoporder.order(body.points, body.preset, dials, started=started))
    except routing.DeadlineExceeded:
        refusal = _error(503, "Finding the best order took too long; try again shortly.")
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        return refusal


# Snapping an opened GPX track to the map's ways (core.map_match; PLAN.md, Import: map matching):
# signed out or in, counted as routing is, and nothing kept. The body is the track's line, up to
# map_match.MAX_POINTS points, which is larger than a route request, so it is read here with its
# own cap rather than through `json_body_only`.
class MatchOut(Schema):
    line: list[list[float]] = Field(description="The snapped line, [lon, lat] pairs.")
    matched_share: float = Field(
        description="The share of the track's points the matcher put on a way, 0 to 1."
    )


@api.post(
    "/match",
    response={
        200: MatchOut,
        400: ErrorOut,
        422: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        503: BusyOut,
    },
    summary="Snap an opened GPX track to the routable network on a ride type's graph",
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.ROUTING_IN_FLIGHT),
    ratelimit.rate_limited(ratelimit.ROUTING),
    errors_as_json,
)
def match_track(request):
    body, refusal = _json_body(request, map_match.MAX_BYTES)
    if refusal is not None:
        return refusal
    if not isinstance(body, dict) or set(body) - {"points", "preset", "trails_off", "assist"}:
        return _error(400, "Send the track as an object with points and a ride type.")
    preset = body.get("preset", "default")
    if not isinstance(preset, str) or preset not in presets.PRESETS:
        return _error(400, "Not a ride type this planner offers.")
    trails_off = body.get("trails_off", False)
    assist = body.get("assist", False)
    if not isinstance(trails_off, bool) or not isinstance(assist, bool):
        return _error(400, "trails_off and assist are true or false.")
    try:
        points = map_match.checked_points(body.get("points"))
    except map_match.TrackProblem as problem:
        return _error(400, str(problem))
    try:
        answer = map_match.match(
            points,
            preset,
            getattr(request, "routing_started", None),
            trails_off=trails_off,
            assist=assist,
        )
    except routing.RouterRefused:
        return _error(
            422,
            "No street or path along the track could be found for this ride type: it may run"
            " where the map has no way, or where this ride type does not ride.",
        )
    except (routing.RouterUnavailable, routing.DeadlineExceeded):
        refusal = _error(503, "Snapping the track took too long or the router is busy; try again.")
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        return refusal
    return JsonResponse(answer)


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
        trails_off=body.trails_off,
        mtb_level=body.mtb_level,
        mtb_preferred=body.mtb_preferred,
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
    trail: bool = Field(
        default=False,
        description=(
            "A tap on the mountain-bike trail layer: describe the nearest such trail, ahead"
            " of a road beside it."
        ),
    )

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


class MoreLinkOut(Schema):
    label: str
    url: str
    system: str | None = Field(default=None, description="MORE's name for the trail system.")


class SegmentInfoOut(Schema):
    found: bool = Field(description="Whether a road or path is within reach of the spot.")
    title: str = Field(
        description="The way's name, 'Unnamed road' or 'Unnamed path', or 'No road here'."
    )
    tier: int | None = Field(default=None, description="Traffic stress, 1-4, or 5 for Avoid.")
    step: float | None = Field(
        default=None,
        description=(
            "The exact step, half steps included (1, 1.5, ... 4.5, 5); `tier` is its whole level."
        ),
    )
    half_steps: bool | None = Field(
        default=None,
        description="Whether the road data can hold a half step yet; null with no road.",
    )
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
    more: MoreLinkOut | None = Field(
        default=None,
        description=(
            "A mountain-bike trail's link to MORE (Mid-Atlantic Off-Road Enthusiasts): its"
            " system's page (trailheads, trail info, the day's conditions), or MORE's trail"
            " guide where its names place it in no system; null on any other way."
        ),
    )
    mtb_trail: bool = Field(
        default=False,
        description=(
            "A mountain-bike trail the trail layer draws: its elevation profile is at"
            " /api/trails/{osm_way_id}/profile, and it has no traffic lines."
        ),
    )
    trail_open: str | None = Field(
        default=None,
        description=(
            "On a mountain-bike trail: 'offroad' where the Gravel, Mountain Goat and"
            " Mountain Bike ride types may route through it (Mountain Bike up to the"
            " rider's level), 'mtb' where only Mountain Bike may, null where none may."
        ),
    )
    trail_level: int | None = Field(
        default=None,
        description=(
            "On a mountain-bike trail: the level (1-4) Mountain Bike's hardest-level"
            " choice reads it at."
        ),
    )
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
    found = segment_info.segment_info(params.lat, params.lon, params.trail)
    response["Cache-Control"] = f"private, max-age={SEGMENT_INFO_MAX_AGE_S}"
    return Status(200, {**found, "attribution": list(SEGMENT_INFO_ATTRIBUTION)})


# --- The scenic roads near a point (v0.12.3; core.scenic_near) --------------------------------
#
# GET /api/scenic-roads: the rustic roads, scenic byways, East Coast Greenway and US Bicycle
# Routes near a point, for the assistant connector's `scenic_roads_near` (the owner,
# 2026-10-25: "The goal would be for a new user to be able to make routes like this"). Read
# only, signed out, counted and limited as the road panel is.


class ScenicRoadsIn(Schema):
    lat: Coordinate
    lon: Coordinate
    miles: float = Field(
        default=5.0, gt=0, le=scenic_near.MAX_RADIUS_MI, description="How far to look, miles."
    )
    designation: str = Field(
        default="",
        max_length=40,
        description="Only roads whose designation holds this word: 'rustic', 'byway'.",
    )

    @model_validator(mode="after")
    def point_inside(self):
        _check_inside(self.lat, self.lon)
        return self


class ScenicRoadOut(Schema):
    road: str | None = Field(description="Its name, from the router; null where none is mapped.")
    designation: str = Field(description='As the road panel says it, several joined by " · ".')
    miles: float = Field(description="Its miles within reach.")
    lts_miles: dict[str, float] = Field(description='Miles at each stress: {"LTS 2": 1.4}.')
    lon_lat: list[float] = Field(description="A point on it: where a via point puts a route on it.")
    nearest: list[float] = Field(description="Its point nearest the one asked about.")
    away_mi: float


class ScenicRoadsOut(Schema):
    roads: list[ScenicRoadOut] = Field(description="Nearest first, at most 25.")
    attribution: list[str]


SCENIC_ROADS_ATTRIBUTION = (
    "© OpenStreetMap contributors (ODbL)",
    "Montgomery County Planning",
    "MDOT SHA",
)


@api.get(
    "/scenic-roads",
    response={
        200: ScenicRoadsOut,
        400: ErrorOut,
        403: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        503: ErrorOut,
    },
    summary="The rustic roads, scenic byways and named bike routes near a point",
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.GEOCODE_IN_FLIGHT, ratelimit.name_slots),
    ratelimit.rate_limited(ratelimit.SCENIC_ROADS),
    ratelimit.rate_limited(ratelimit.SCENIC_ROADS_BURST),
    same_site_only,
    errors_as_json,
)
def scenic_roads(request, params: Query[ScenicRoadsIn], response: HttpResponse):
    try:
        found = scenic_near.near(params.lon, params.lat, params.miles, params.designation)
    except scenic_near.TimedOut:
        return Status(503, {"error": "the scenic road search took too long; try a smaller area"})
    response["Cache-Control"] = f"private, max-age={SEGMENT_INFO_MAX_AGE_S}"
    return Status(200, {"roads": found, "attribution": list(SCENIC_ROADS_ATTRIBUTION)})


# --- Climbs near a point (v0.12.3; core.climbs_near) ----------------------------------------
#
# GET /api/climbs-near: the categorised climbs within reach of a point, from the Climbs layer's
# file, for the assistant connector's `climbs_near` (the owner, 2026-10-25, of hill repeats for
# intervals: "Yep, add that"). Read only, signed out, counted and limited.


class ClimbsNearIn(Schema):
    lat: Coordinate
    lon: Coordinate
    miles: float = Field(
        default=5.0, gt=0, le=climbs_near.MAX_RADIUS_MI, description="How far to look, miles."
    )
    min_grade: float = Field(
        default=0.0, ge=0, le=30, description="Only climbs at least this steep on average, %."
    )
    on_minutes: float = Field(
        default=0.0, ge=0, le=60, description="Only climbs an effort this long fits up."
    )
    pace_mph: float = Field(default=18.0, ge=4, le=35, description="The effort's flat pace.")
    paved_only: bool = Field(default=False, description="Leave out gravel and MTB climbs.")
    quiet_only: bool = Field(default=False, description="Leave out climbs mostly on LTS 3+.")
    steepest: bool = Field(default=False, description="Steepest first, not nearest first.")

    @model_validator(mode="after")
    def point_inside(self):
        _check_inside(self.lat, self.lon)
        return self


class ClimbNearOut(Schema):
    id: str = Field(description="The climb's id in the Climbs layer's file.")
    name: str | None = Field(description="From its roads and the hill it runs up; null if none.")
    category: str = Field(description='"5" to "1" or "HC".')
    miles: float
    gain_ft: int
    grade_pct: float = Field(description="Average grade, %.")
    foot: list[float] = Field(description="Where it starts, [lon, lat].")
    summit: list[float] = Field(description="Where it tops out, [lon, lat].")
    through: list[list[float]] = Field(
        description="Points up it, near the foot to near the summit: via points that keep a"
        " plan on the climb."
    )
    surface: str = Field(description='"road", "path", "gravel" or "mountain-bike trail".')
    busy: bool | None = Field(
        description="Most of its roads are LTS 3 or higher; null where the file does not say."
    )
    away_mi: float


class ClimbsNearOut(Schema):
    climbs: list[ClimbNearOut] = Field(description="Nearest (or steepest) first, at most 25.")
    attribution: list[str]


CLIMBS_NEAR_ATTRIBUTION = (
    "© OpenStreetMap contributors (ODbL)",
    "USGS 3D Elevation Program",
)


@api.get(
    "/climbs-near",
    response={200: ClimbsNearOut, 400: ErrorOut, 403: ErrorOut, 429: ErrorOut, 503: ErrorOut},
    summary="The categorised climbs near a point",
)
@decorate_view(
    ratelimit.rate_limited(ratelimit.CLIMBS_NEAR),
    ratelimit.rate_limited(ratelimit.CLIMBS_NEAR_BURST),
    same_site_only,
    errors_as_json,
)
def climbs_near_point(request, params: Query[ClimbsNearIn], response: HttpResponse):
    try:
        found = climbs_near.near(
            params.lon,
            params.lat,
            params.miles,
            min_grade=params.min_grade,
            on_minutes=params.on_minutes,
            pace_mph=params.pace_mph,
            paved_only=params.paved_only,
            quiet_only=params.quiet_only,
            steepest=params.steepest,
        )
    except climbs_near.Unavailable:
        return Status(503, {"error": "this server has no climbs file"})
    response["Cache-Control"] = f"private, max-age={SEGMENT_INFO_MAX_AGE_S}"
    return Status(200, {"climbs": found, "attribution": list(CLIMBS_NEAR_ATTRIBUTION)})


# --- The road panel's street photo (v0.7.0; core.street_photo) ------------------------------
#
# GET /api/street-photo: the newest Mapillary photo of the road at a point on it, looked up
# server-side so the Mapillary token never reaches a browser. 204 where no photo can be looked
# up (no token on this server, or Mapillary not answering): the panel then says nothing of one.


class StreetPhotoIn(Schema):
    lon: float = Field(ge=-180, le=180, description="The point on the road (the panel's on_way).")
    lat: float = Field(ge=-90, le=90)
    way: int | None = Field(
        default=None, ge=1, description="The road's OSM way id: the photo faces along it."
    )


class StreetPhotoOut(Schema):
    found: bool
    words: str | None = Field(default=None, description='"No street photo here." when none.')
    image_url: str | None = Field(
        default=None, description="The image, served by this server from Mapillary's host."
    )
    viewer_url: str | None = Field(default=None, description="Mapillary's viewer at the image.")
    captured: str | None = Field(default=None, description="The day it was taken, ISO 8601.")
    date_words: str | None = Field(default=None, description='"Photo from June 2021".')
    creator: str | None = Field(default=None, description="Its creator on Mapillary, if named.")
    credit: str | None = None
    credit_url: str | None = None
    licence: str | None = None
    licence_url: str | None = None


@api.get(
    "/street-photo",
    response={200: StreetPhotoOut, 204: None, 400: ErrorOut, 403: ErrorOut, 429: ErrorOut},
    summary="The newest Mapillary photo of the road at a point on it",
)
@decorate_view(ratelimit.rate_limited(ratelimit.STREET_PHOTO), same_site_only, errors_as_json)
def street_photo_view(request, params: Query[StreetPhotoIn], response: HttpResponse):
    from . import street_photo

    found = street_photo.client.photo(params.lon, params.lat, params.way)
    if found is None:
        return Status(204, None)
    response["Cache-Control"] = "private, max-age=600"
    return Status(200, found)


@api.get(
    "/street-photo/image/{image_id}",
    response={200: None, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut, 429: ErrorOut},
    summary="A street photo's image file, fetched from Mapillary for the page",
)
@decorate_view(ratelimit.rate_limited(ratelimit.STREET_PHOTO), same_site_only, errors_as_json)
def street_photo_image_view(request, image_id: str):
    from . import street_photo

    if not image_id.isdigit() or len(image_id) > 30:
        return Status(404, {"error": "No such photo."})
    body = street_photo.client.image(image_id)
    if body is None:
        return Status(404, {"error": "No such photo."})
    served = HttpResponse(body, content_type="image/jpeg")
    served["Cache-Control"] = "private, max-age=3600"
    served["X-Content-Type-Options"] = "nosniff"
    return served


# --- One climb's elevation profile, for the map's climb card ------------------------

CLIMB_PROFILE_MAX_AGE_S = 86_400


class ClimbProfileOut(Schema):
    """One climb of the Climbs layer, as the map's climb card draws it
    (`core.climbprofile`): the file's figures, the steepest grade, and the heights
    along it from its foot to its summit, as the route chart's `profile`."""

    id: str
    category: str
    length_m: int
    gain_m: float
    avg_grade_pct: float
    max_grade_pct: float | None = Field(
        description=(
            "The steepest grade on it, percent, read across four samples as the route chart"
            " reads it."
        )
    )
    interval_m: int
    m: list[int] = Field(description="Metres from the climb's foot to each sample.")
    elevation_m: list[float | None]
    grade_pct: list[float | None]


@api.get(
    "/climbs/{climb_id}/profile",
    response={200: ClimbProfileOut, 404: ErrorOut, 429: ErrorOut, 500: ErrorOut, 503: ErrorOut},
    summary="One climb's elevation profile, from its foot to its summit (the map's climb card)",
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.ROUTING_IN_FLIGHT),
    ratelimit.rate_limited(ratelimit.CLIMB_PROFILE),
    errors_as_json,
)
def climb_profile(request, climb_id: str, response: HttpResponse):
    """Read-only: a climb is named by its id in the Climbs layer's file, never by a line,
    and its heights are the router's (USGS 3DEP), as a route's are."""
    if not (1 <= len(climb_id) <= 32 and climb_id.isalnum()):
        return Status(404, {"error": "There is no such climb."})
    try:
        climb = climbprofile.find(climb_id)
        if climb is None:
            return Status(404, {"error": "There is no such climb."})
        body = climbprofile.profile(climb)
    except climbprofile.Unavailable as error:
        logger.warning("climb profile unavailable: %s", error)
        refusal = JsonResponse(
            {"error": "The climb's elevation is not available right now. Try again shortly."},
            status=503,
        )
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        return refusal
    if body is None:
        return Status(404, {"error": "There is no elevation for this climb."})
    response["Cache-Control"] = f"public, max-age={CLIMB_PROFILE_MAX_AGE_S}"
    return Status(200, body)


# --- One mountain-bike trail's elevation profile, for the road panel ----------------

TRAIL_PROFILE_MAX_AGE_S = 86_400


class TrailProfileOut(Schema):
    """A mountain-bike trail's heights along it (`core.trailprofile`; the owner,
    2026-10-19: "Include an elevation profile of the trail if possible"), as the route
    chart's `profile`, with its climbing, descending and steepest grade."""

    way: int
    length_m: int
    gain_m: float
    loss_m: float
    max_grade_pct: float | None = Field(
        description=(
            "The steepest grade on it, either way, percent, read as the route chart reads it."
        )
    )
    interval_m: int
    m: list[int] = Field(description="Metres from the way's first point to each sample.")
    elevation_m: list[float | None]
    grade_pct: list[float | None]
    start: list[float] | None = Field(
        default=None, description="The way's first point, [lon, lat]: the chart's left end."
    )
    end: list[float] | None = Field(
        default=None, description="The way's last point, [lon, lat]: the chart's right end."
    )


@api.get(
    "/trails/{way_id}/profile",
    response={200: TrailProfileOut, 404: ErrorOut, 429: ErrorOut, 500: ErrorOut, 503: ErrorOut},
    summary="One mountain-bike trail's elevation profile (the road panel, for a tapped trail)",
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.ROUTING_IN_FLIGHT),
    ratelimit.rate_limited(ratelimit.TRAIL_PROFILE),
    errors_as_json,
)
def trail_profile(request, way_id: int, response: HttpResponse):
    """Read-only: a trail is named by its OSM way id and read from the live table, never
    by a line; only a way the mountain-bike trail layer draws is answered."""
    if not 0 < way_id < 2**53:
        return Status(404, {"error": "There is no such trail."})
    try:
        body = trailprofile.profile(way_id)
    except trailprofile.Unavailable as error:
        logger.warning("trail profile unavailable: %s", error)
        refusal = JsonResponse(
            {"error": "The trail's elevation is not available right now. Try again shortly."},
            status=503,
        )
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        return refusal
    if body is None:
        return Status(404, {"error": "There is no elevation for this trail."})
    response["Cache-Control"] = f"public, max-age={TRAIL_PROFILE_MAX_AGE_S}"
    return Status(200, body)


# --- Who is asking, and the road panel's stress editor -----------------------------
#
# GET /api/me and the three /api/stress-edits endpoints (OWNER-DECISIONS 441g, 441h, 441m, 460;
# core.stress_edits). The first authenticated writes in this API, so every one of these has
# all of: a session of an account in standing (401 without), instance-admin standing (403,
# and a refused write is audited), a CSRF token on writes (Django's own check, which Ninja
# does not apply to a view it has marked exempt), the same-site check, a JSON body of bounded
# size, and a count - per client address first, then per account. Nothing here carries a
# name or an id of a person: /api/me answers three yes/no flags, a path carries an OSM way id
# or an edit id, and a body is JSON, never a query string.

ME_MAX_AGE = "no-store"


class MeOut(Schema):
    signed_in: bool
    can_change_lts: bool = Field(
        description="An active instance admin: the road panel offers Change LTS."
    )
    can_suggest: bool = Field(
        description="The road panel offers Suggest a change (core.suggestions.may_suggest)."
    )
    can_review_closures: bool = Field(
        default=False,
        description=(
            "A reviewer: the road panel offers Mark closed, and Review lists closure reports"
            " (core.reviewed_closures.may_review)."
        ),
    )
    sign_in: bool = Field(
        default=False,
        description=(
            "Whether this server can sign anyone in (both Discord keys are set): the page offers"
            " Sign in with Discord only when it is true."
        ),
    )


def _private(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = ME_MAX_AGE
    response["Vary"] = "Cookie"
    return response


def _stress_error(status: int, message: str, field: str | None = None, code: str | None = None):
    body: dict = {"error": message}
    if field:
        body["field"] = field
    if code:
        body["code"] = code
    return _private(JsonResponse(body, status=status))


class StressEditErrorOut(Schema):
    error: str
    field: str | None = Field(default=None, description="The form field the error is about.")
    code: str | None = None


def same_site_editor(view):
    """`same_site_only`, with a sentence that fits the editor."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        site = request.META.get("HTTP_SEC_FETCH_SITE", "").strip().lower()
        if site and site not in ("same-origin", "none"):
            return _stress_error(403, "This answers this site's own pages only.")
        return view(request, *args, **kwargs)

    return wrapped


def _refused(request, user, detail: str) -> None:
    """Audit a refused write. Written here, outside any transaction the refusal unwound."""
    from .models import AuditLogEntry

    audit.record(
        user,
        "stress_edit",
        "override",
        "",
        AuditLogEntry.Outcome.REFUSED,
        detail=f"{request.method} {request.path.split('?')[0]}: {detail}"[:2000],
    )


def instance_admin_only(*, audited: bool, doing: str = "change traffic stress"):
    """A session of an active instance admin, or 401 (no session) or 403.

    `audited`: a write refused to a signed-in account is written to the audit log (the
    plan: every refused write is). A read refused is not, as the admin's page views are not.
    `doing` finishes the refusals' sentences ("Sign in to ...").
    """

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not signed_in(request):
                return _stress_error(401, f"Sign in to {doing}.", code="signed_out")
            user = request.user
            if not getattr(user, "is_instance_admin", False):
                if audited:
                    _refused(request, user, "not an instance admin")
                return _stress_error(403, f"Only an instance admin can {doing}.", code="not_admin")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _no_view():  # pragma: no cover - the callback Django's CSRF check is asked about
    return None


def csrf_protected(view):
    """Refuse a write that does not carry the CSRF token (Django's own check).

    Ninja marks every view it serves `csrf_exempt` and only checks the token itself for
    its own cookie authenticators, so `CsrfViewMiddleware` lets these through unchecked.
    The check is therefore made here, with the middleware's own `process_view`: the
    `X-CSRFToken` header against the `csrftoken` cookie, and the Origin or Referer against
    the host or `CSRF_TRUSTED_ORIGINS` on HTTPS.
    """
    from django.middleware.csrf import CsrfViewMiddleware

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        refusal = CsrfViewMiddleware(lambda r: None).process_view(request, _no_view, (), {})
        if refusal is not None:
            _refused(request, request.user, "missing or wrong CSRF token")
            return _stress_error(
                403,
                "This page's security token is missing or out of date. Reload the page and "
                "try again.",
                code="csrf",
            )
        return view(request, *args, **kwargs)

    return wrapped


@api.get(
    "/me",
    response={200: MeOut, 403: ErrorOut, 429: ErrorOut, 500: ErrorOut},
    summary="Yes/no flags: signed in, may change traffic stress, may suggest, sign-in offered",
)
@decorate_view(
    ratelimit.rate_limited(ratelimit.ME),
    same_site_only,
    errors_as_json,
)
def me(request, response: HttpResponse):
    """No name and no id, so nothing here can leak into a link or a log."""
    from django.middleware.csrf import get_token

    from . import reviewed_closures, suggestions

    signed = signed_in(request)
    can_change = bool(signed and getattr(request.user, "is_instance_admin", False))
    can_suggest = bool(signed and suggestions.may_suggest(request.user))
    can_review = bool(signed and reviewed_closures.may_review(request.user))
    if can_change or can_suggest or can_review:
        # Sets the `csrftoken` cookie the editor sends back as `X-CSRFToken`.
        get_token(request)
    _private(response)
    from .auth_views import sign_in_available

    return Status(
        200,
        {
            "signed_in": signed,
            "can_change_lts": can_change,
            "can_suggest": can_suggest,
            "can_review_closures": can_review,
            "sign_in": sign_in_available(),
        },
    )


# GET and POST /api/me/go: a signed-in rider's own My Go (UI-CLEANUP, the owner's choice 2 of
# 2026-10-11; core.models.MyGo): the view the app opens in, the ride type Go uses and the Home the
# Go sheet's Home chip rides to. The rider's own settings and nobody else's, so no standing is
# needed beyond being signed in; a write carries the CSRF token (set by the GET) and is counted
# per address and per account. Signed out it is 401: the front end keeps the same choices in the
# browser instead.


class HomeIn(Schema):
    model_config = ConfigDict(extra="forbid")

    lon: StrictFloat
    lat: StrictFloat
    label: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def inside_coverage(self):
        west, south, east, north = settings.COVERAGE_BBOX
        if not (west <= self.lon <= east and south <= self.lat <= north):
            raise ValueError("Home is outside the area this map covers")
        return self


class MyGoIn(Schema):
    """The whole of My Go: what is left out is cleared (an empty `open_in` is by screen size,
    an empty `ride` is Default, a null `home` is none)."""

    model_config = ConfigDict(extra="forbid")

    open_in: Literal["", "go", "plan"] = ""
    ride: str = Field(default="", max_length=32)
    home: HomeIn | None = None

    @field_validator("ride")
    @classmethod
    def known_ride(cls, ride: str) -> str:
        ride = presets.resolve_preset(ride)
        if ride and ride not in presets.PRESETS:
            raise ValueError("not a ride type this planner offers")
        return ride


class HomeOut(Schema):
    lon: float
    lat: float
    label: str


class MyGoOut(Schema):
    open_in: Literal["", "go", "plan"] = Field(
        description="Empty: by screen size (a phone opens in Go, a wider screen in Plan)."
    )
    ride: str = Field(description="A ride type id; empty is Default.")
    home: HomeOut | None


def signed_in_only(view):
    """A session of an account in standing, or 401: My Go is the rider's own."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not signed_in(request):
            return _stress_error(401, "Sign in to keep My Go with your account.", code="signed_out")
        return view(request, *args, **kwargs)

    return wrapped


def _my_go_out(row) -> dict:
    home = None
    if row is not None and row.home_lat is not None and row.home_lon is not None:
        home = {"lon": row.home_lon, "lat": row.home_lat, "label": row.home_label}
    return {
        "open_in": row.open_in if row is not None else "",
        "ride": presets.resolve_preset(row.ride) if row is not None else "",
        "home": home,
    }


@api.get(
    "/me/go",
    response={200: MyGoOut, 401: StressEditErrorOut, 403: StressEditErrorOut, 429: ErrorOut},
    summary="The signed-in rider's My Go: the view to open in, Go's ride type, and Home",
)
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def my_go_read(request, response: HttpResponse):
    from django.middleware.csrf import get_token

    from .models import MyGo

    # Sets the `csrftoken` cookie the save sends back as `X-CSRFToken`.
    get_token(request)
    _private(response)
    return Status(200, _my_go_out(MyGo.objects.filter(user=request.user).first()))


@api.post(
    "/me/go",
    response={
        200: MyGoOut,
        400: StressEditErrorOut,
        401: StressEditErrorOut,
        403: StressEditErrorOut,
        429: ErrorOut,
    },
    summary="Save the signed-in rider's My Go (the whole of it)",
)
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.MY_GO_WRITES),
    csrf_protected,
    signed_in_only,
    json_body_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def my_go_save(request, body: MyGoIn, response: HttpResponse):
    from .models import MyGo, SharedRoute

    home = body.home
    before = MyGo.objects.filter(user=request.user).values_list("home_lon", "home_lat").first()
    after = (round(home.lon, 5), round(home.lat, 5)) if home else (None, None)
    if before is not None and before != (None, None) and tuple(before) != after:
        # Home cleared or moved: a link's frozen circle round the old Home is a point near it, so
        # it goes, and those links lose their image rather than show the old Home uncovered.
        SharedRoute.objects.filter(owner=request.user, preview_zone__isnull=False).update(
            preview_zone=None, preview_image=False, preview_png=None, preview_key=""
        )
    row, _ = MyGo.objects.update_or_create(
        user=request.user,
        defaults={
            "open_in": body.open_in,
            "ride": body.ride,
            # About a metre: all a Home chip needs, and no finer than the rider picked it.
            "home_lat": round(home.lat, 5) if home else None,
            "home_lon": round(home.lon, 5) if home else None,
            "home_label": home.label.strip() if home else "",
        },
    )
    _private(response)
    return Status(200, _my_go_out(row))


# GET and POST /api/me/places: a signed-in rider's favorite places (Stephen 2026-10-26: "For
# signed in users, allow for favorite destinations"; core.models.MyGo.places). Go's Favorites chip
# lists Home first, then Work once set, then these. Saved whole, on their own (a My Go save never
# touches them), with My Go's guards; never logged, and deleted with the account.

FAVORITE_PLACES_MAX = 20


class FavoritePlaceIn(Schema):
    model_config = ConfigDict(extra="forbid")

    lon: StrictFloat
    lat: StrictFloat
    label: str = Field(min_length=1, max_length=120)
    # Work (Stephen 2026-10-26: "Home and if set work would be the top 2 favorites"): at most one.
    work: bool = False

    @model_validator(mode="after")
    def inside_coverage(self):
        west, south, east, north = settings.COVERAGE_BBOX
        if not (west <= self.lon <= east and south <= self.lat <= north):
            raise ValueError("A favorite place is outside the area this map covers")
        if not self.label.strip():
            raise ValueError("A favorite place needs a name")
        return self


class FavoritePlacesIn(Schema):
    """The whole list, in the rider's order: what is left out is removed."""

    model_config = ConfigDict(extra="forbid")

    places: list[FavoritePlaceIn] = Field(default_factory=list, max_length=FAVORITE_PLACES_MAX)

    @model_validator(mode="after")
    def one_work_each_place_once(self):
        if sum(1 for p in self.places if p.work) > 1:
            raise ValueError("Only one place can be Work")
        spots = [(round(p.lon, 5), round(p.lat, 5)) for p in self.places]
        if len(set(spots)) != len(spots):
            raise ValueError("A place is in the list twice")
        return self


class FavoritePlaceOut(Schema):
    lon: float
    lat: float
    label: str
    work: bool


class FavoritePlacesOut(Schema):
    places: list[FavoritePlaceOut]


def _places_out(row) -> dict:
    kept = row.places if row is not None and isinstance(row.places, list) else []
    return {
        "places": [
            {"lon": p["lon"], "lat": p["lat"], "label": p["label"], "work": bool(p.get("work"))}
            for p in kept
            if isinstance(p, dict) and {"lon", "lat", "label"} <= set(p)
        ]
    }


@api.get(
    "/me/places",
    response={
        200: FavoritePlacesOut,
        401: StressEditErrorOut,
        403: StressEditErrorOut,
        429: ErrorOut,
    },
    summary="The signed-in rider's favorite places (Work among them)",
)
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def favorite_places_read(request, response: HttpResponse):
    from django.middleware.csrf import get_token

    from .models import MyGo

    get_token(request)
    _private(response)
    return Status(200, _places_out(MyGo.objects.filter(user=request.user).first()))


@api.post(
    "/me/places",
    response={
        200: FavoritePlacesOut,
        400: StressEditErrorOut,
        401: StressEditErrorOut,
        403: StressEditErrorOut,
        429: ErrorOut,
    },
    summary="Save the signed-in rider's favorite places (the whole list)",
)
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.MY_GO_WRITES),
    csrf_protected,
    signed_in_only,
    json_body_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def favorite_places_save(request, body: FavoritePlacesIn, response: HttpResponse):
    from .models import MyGo

    places = [
        {
            # About a metre, as Home.
            "lon": round(p.lon, 5),
            "lat": round(p.lat, 5),
            "label": p.label.strip(),
            **({"work": True} if p.work else {}),
        }
        for p in body.places
    ]
    row, _ = MyGo.objects.update_or_create(user=request.user, defaults={"places": places})
    _private(response)
    return Status(200, _places_out(row))


# Saved settings and saved routes (v0.7.0 plan, "Discord sign-in on, with saved settings and
# routes"; core.accounts, core.models.AccountSettings and SavedRoute). The rider's own and
# nobody else's: signed in, same site, CSRF on every write, counted per account. Signed out it is
# 401 and the page keeps its settings on the device, as before.


def _json_body(request, max_bytes: int):
    """The parsed JSON body, or an error response: the same checks as `json_body_only`, with the
    cap this endpoint needs."""
    content_type = request.META.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        return None, _stress_error(400, "Send the body as application/json.")
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return None, _stress_error(400, "Invalid Content-Length.")
    # The declared length, and the body itself (a missing or understated length is not trusted).
    if declared > max_bytes or len(request.body) > max_bytes:
        return None, _stress_error(400, f"The body is larger than {max_bytes // 1024} KB.")
    try:
        return json.loads(request.body or b"null"), None
    except (ValueError, RecursionError):
        # RecursionError: nesting deeper than the parser's stack (a few thousand "[").
        return None, _stress_error(400, "The body is not JSON.")


def _settings_out(row) -> dict:
    return {
        "settings": row.data if row is not None else None,
        "updated_at": row.updated_at.isoformat() if row is not None else None,
    }


@api.get("/me/settings", summary="The signed-in rider's saved settings (null when none yet)")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def account_settings_read(request):
    from django.middleware.csrf import get_token

    from .models import AccountSettings

    get_token(request)
    row = AccountSettings.objects.filter(user=request.user).first()
    return _private(JsonResponse(_settings_out(row)))


@api.post("/me/settings", summary="Save the signed-in rider's settings (the whole document)")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def account_settings_save(request):
    from . import accounts
    from .models import AccountSettings

    body, refusal = _json_body(request, accounts.SETTINGS_MAX_BYTES + 1024)
    if refusal is not None:
        return refusal
    data = body.get("settings") if isinstance(body, dict) else None
    problem = accounts.settings_problem(data)
    if problem:
        return _stress_error(400, problem, field="settings")
    # One row per account, last write wins (the plan).
    row, _ = AccountSettings.objects.update_or_create(user=request.user, defaults={"data": data})
    return _private(JsonResponse(_settings_out(row)))


# The 311 log (core.report_log; core.models.Report311Log): the whole log, last write wins, like
# the settings. Signed out it is 401 and the log stays on the device.


def _report_log_owner(user) -> str:
    """A tag the page keeps with its copy of the account's 311 log, so a copy left by one account
    is never merged into another's on the same device. Derived from the account with the server's
    key: the same for one account, and no id can be read from it."""
    from django.utils.crypto import salted_hmac

    return salted_hmac("core.report311_log.owner", str(user.pk)).hexdigest()[:24]


def _report_log_out(row, user) -> dict:
    return {
        "entries": row.entries if row is not None else None,
        "updated_at": row.updated_at.isoformat() if row is not None else None,
        "owner": _report_log_owner(user),
    }


@api.get("/me/report311-log", summary="The signed-in rider's 311 log (null when none yet)")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def report311_log_read(request):
    from django.middleware.csrf import get_token

    from .models import Report311Log

    get_token(request)
    row = Report311Log.objects.filter(user=request.user).first()
    return _private(JsonResponse(_report_log_out(row, request.user)))


@api.post("/me/report311-log", summary="Save the signed-in rider's 311 log (the whole log)")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def report311_log_save(request):
    from django.db import transaction

    from . import report_log
    from .models import Report311Log

    body, refusal = _json_body(request, report_log.LOG_MAX_BYTES + 1024)
    if refusal is not None:
        return refusal
    entries = body.get("entries") if isinstance(body, dict) else None
    problem = report_log.log_problem(entries)
    if problem:
        return _stress_error(400, problem, field="entries")
    # Merged with what the account has, by entry (core.report_log.merge_logs), not replaced: a
    # device with an old copy keeps what another device logged. The answer is the merged log.
    with transaction.atomic():
        # The row first (two first saves at once: get_or_create takes the other's), then locked.
        Report311Log.objects.get_or_create(user=request.user, defaults={"entries": []})
        row = Report311Log.objects.select_for_update().get(user=request.user)
        row.entries = report_log.merge_logs(row.entries or [], entries)
        row.save(update_fields=["entries", "updated_at"])
    return _private(JsonResponse(_report_log_out(row, request.user)))


def _route_summary(row) -> dict:
    return {
        "id": row.pk,
        "name": row.name,
        "source": row.source,
        "distance_m": row.distance_m,
        "preset": (row.inputs or {}).get("preset", ""),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        # v0.7.0 closures (core.saved_route_alerts): the closures in force along the line, as
        # last checked; [] where none.
        "closure_alerts": list(row.closure_alerts or []),
    }


def _route_full(row) -> dict:
    return {
        **_route_summary(row),
        "line": row.line,
        "inputs": row.inputs,
        "answer": row.answer,
        "gpx": row.gpx,
    }


def _saved_route(request, route_id: int):
    from .models import SavedRoute

    # Another account's route is "not found", never "forbidden": no route is shared.
    return SavedRoute.objects.filter(user=request.user, pk=route_id).first()


@api.get("/me/routes", summary="The signed-in rider's saved routes, newest first")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def saved_routes_list(request):
    from django.middleware.csrf import get_token

    from .models import SavedRoute

    get_token(request)
    rows = SavedRoute.objects.filter(user=request.user).order_by("-created_at", "-pk")
    return _private(
        JsonResponse(
            {
                "routes": [_route_summary(r) for r in rows.defer("line", "answer")],
                "max": SavedRoute.MAX_PER_ACCOUNT,
            }
        )
    )


@api.post("/me/routes", summary="Save a route: its exact line, the plan's inputs and a name")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def saved_routes_add(request):
    return _add_saved_route(request)


def _add_saved_route(request, versions: bool = True):
    """POST /api/me/routes, and the site's MCP connector's save with `versions` False (it only
    adds; core.connector)."""
    from django.db import transaction

    from . import accounts
    from .models import SavedRoute, User

    body, refusal = _json_body(request, accounts.ROUTE_MAX_BYTES)
    if refusal is not None:
        return refusal
    if not isinstance(body, dict):
        return _stress_error(400, "Send the route as an object.")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > accounts.NAME_MAX:
        return _stress_error(
            400, f"Give the route a name of up to {accounts.NAME_MAX} characters.", field="name"
        )
    source = body.get("source", SavedRoute.Source.PLAN)
    if source not in SavedRoute.Source.values:
        return _stress_error(400, "Not a kind of route this planner saves.", field="source")
    line = body.get("line")
    problem = accounts.line_problem(line)
    if problem:
        return _stress_error(400, problem, field="line")
    distance = body.get("distance_m")
    if not accounts._finite(distance) or distance <= 0:
        return _stress_error(400, "The route's distance is missing.", field="distance_m")
    inputs = body.get("inputs", {})
    problem = accounts.inputs_problem(inputs)
    if problem:
        return _stress_error(400, problem, field="inputs")
    # An opened file keeps the route shown for it too (v0.9.0, "share the exact route"), so it
    # reopens as that line, followed by the rules or exactly (`follows_exactly`).
    answer = body.get("answer")
    if answer is not None and not isinstance(answer, dict):
        return _stress_error(400, "Send the route's answer as an object.", field="answer")
    if answer is not None:
        answer, problem = _clean_answer(answer)
        if problem:
            return _stress_error(400, problem, field="answer")
    gpx = body.get("gpx", "") or ""
    if not isinstance(gpx, str) or (gpx and source != SavedRoute.Source.GPX):
        return _stress_error(400, "Only an opened GPX file keeps its text.", field="gpx")
    version_of = body.get("version_of")
    if version_of is not None and not versions:
        return _stress_error(400, "An assistant only adds routes.", field="version_of")
    if version_of is not None:
        # Saved again: a new latest version of that route, not another route (so not counted
        # toward the account's cap).
        if not isinstance(version_of, int) or isinstance(version_of, bool):
            return _stress_error(400, "Not a saved route.", field="version_of")
        content = {
            "source": source,
            "line": line,
            "distance_m": float(distance),
            "inputs": inputs,
            "answer": answer,
            "gpx": gpx,
        }
        return _save_version(request, version_of, name.strip(), content)
    with transaction.atomic():
        # Taken in turn per account, so two saves at once cannot both pass the cap.
        User.objects.select_for_update().filter(pk=request.user.pk).first()
        if SavedRoute.objects.filter(user=request.user).count() >= SavedRoute.MAX_PER_ACCOUNT:
            return _stress_error(
                409,
                f"You have {SavedRoute.MAX_PER_ACCOUNT} saved routes, the most an account keeps."
                " Delete one in My routes to save this one.",
                code="full",
            )
        row = SavedRoute.objects.create(
            user=request.user,
            name=name.strip(),
            source=source,
            line=line,
            distance_m=float(distance),
            inputs=inputs,
            answer=answer,
            gpx=gpx,
        )
    from . import saved_route_alerts

    saved_route_alerts.check(row)
    return _private(JsonResponse(_route_summary(row), status=201))


# The rider's Garmin connection (core.garmin_views; the owner, 2026-10-23): Settings shows it and
# disconnects it. Connecting is a page visit (/auth/garmin/start), since Garmin's consent is a page.


def _garmin_out(user) -> dict:
    from . import garmin
    from .models import GarminLink

    link = GarminLink.objects.filter(user=user).first()
    return {
        "available": garmin.offered(),
        "connected": link is not None,
        "connected_at": link.created_at.isoformat() if link else None,
        "last_used_at": link.last_used_at.isoformat() if link and link.last_used_at else None,
    }


@api.get("/me/garmin", summary="Whether the rider's Garmin account is connected")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def garmin_read(request):
    return _private(JsonResponse(_garmin_out(request.user)))


@api.post("/me/garmin/delete", summary="Disconnect the rider's Garmin account")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def garmin_delete(request):
    from .garmin_views import disconnect

    disconnect(request.user)
    return _private(JsonResponse(_garmin_out(request.user)))


# Garmin's own per-rider cap is 200 calls a day; a send is one or two.
GARMIN_COURSE_MAX_BYTES = 2 * 1024 * 1024


@api.post("/me/garmin/courses", summary="Send the route shown to the rider's Garmin as a course")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def garmin_course_send(request):
    """Body: {"name", "preset", "line": [[lon, lat, ele], ...], "saved_route": id or null}.
    200 {"sent": "added" | "updated"}; 409 {"error", "code": "not_connected"} when there is no
    live connection (Settings offers Connect again); 502 {"error"} when Garmin refused or could
    not be reached (the app then hands the file on); 400 for a line no course can be made from."""
    from . import garmin, garmin_courses

    body, error = _json_body(request, GARMIN_COURSE_MAX_BYTES)
    if error is not None:
        return error
    if not isinstance(body, dict):
        return _stress_error(400, "Send an object.")
    saved = body.get("saved_route")
    if saved is not None and (not isinstance(saved, int) or isinstance(saved, bool)):
        return _stress_error(400, "saved_route is a route's id, or null.", field="saved_route")
    try:
        course = garmin_courses.build(
            str(body.get("name") or ""), str(body.get("preset") or ""), body.get("line")
        )
    except garmin_courses.BadLine as bad:
        return _stress_error(400, str(bad), field="line")
    try:
        sent, _course_id = garmin_courses.send(request.user, course, saved)
    except garmin.NotConnected as ended:
        return _stress_error(409, str(ended), code="not_connected")
    except garmin.GarminError as failed:
        return _stress_error(502, str(failed))
    return _private(JsonResponse({"sent": sent}))


# The rider's Wahoo connection (core.wahoo_views; the owner, 2026-10-23), as Garmin's above.


def _wahoo_out(user) -> dict:
    from . import wahoo
    from .models import WahooLink

    link = WahooLink.objects.filter(user=user).first()
    return {
        "available": wahoo.offered(),
        "connected": link is not None,
        "connected_at": link.created_at.isoformat() if link else None,
        "last_used_at": link.last_used_at.isoformat() if link and link.last_used_at else None,
    }


@api.get("/me/wahoo", summary="Whether the rider's Wahoo account is connected")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def wahoo_read(request):
    return _private(JsonResponse(_wahoo_out(request.user)))


@api.post("/me/wahoo/delete", summary="Disconnect the rider's Wahoo account")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def wahoo_delete(request):
    from .wahoo_views import disconnect

    disconnect(request.user)
    return _private(JsonResponse(_wahoo_out(request.user)))


# The FIT file as base64 (at most 2 MB, core.wahoo_routes.MAX_FIT_BYTES) and the line beside it;
# the account's paths take bodies up to 5 MB (Caddyfile @routes_body, the beta's nginx).
WAHOO_ROUTE_MAX_BYTES = 4 * 1024 * 1024


@api.post("/me/wahoo/routes", summary="Send the route shown to the rider's Wahoo app")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def wahoo_route_send(request):
    """Body: {"name", "line": [[lon, lat, ele], ...], "fit": base64, "saved_route": id or null}.
    200 {"sent": "added" | "updated"}; 409 {"error", "code": "not_connected"} when there is no
    live connection; 502 {"error"} when Wahoo refused or could not be reached; 400 for a line or
    file no route can be made from. In each failure the app hands the file on instead."""
    from . import wahoo, wahoo_routes

    body, error = _json_body(request, WAHOO_ROUTE_MAX_BYTES)
    if error is not None:
        return error
    if not isinstance(body, dict):
        return _stress_error(400, "Send an object.")
    saved = body.get("saved_route")
    if saved is not None and (not isinstance(saved, int) or isinstance(saved, bool)):
        return _stress_error(400, "saved_route is a route's id, or null.", field="saved_route")
    try:
        form = wahoo_routes.build(str(body.get("name") or ""), body.get("line"), body.get("fit"))
    except wahoo_routes.BadLine as bad:
        return _stress_error(400, str(bad), field="line")
    try:
        sent, _route_id = wahoo_routes.send(request.user, form, saved)
    except wahoo.NotConnected as ended:
        return _stress_error(409, str(ended), code="not_connected")
    except wahoo.WahooError as failed:
        return _stress_error(502, str(failed))
    return _private(JsonResponse({"sent": sent}))


# Assistant apps the rider connected through the site's own MCP connector (core.connector; the
# owner, 2026-10-19: "Sure, add that in"): listed in Settings, each with Disconnect, which ends
# that app's access at once.


def _connected_app_out(grant) -> dict:
    return {
        "id": grant.pk,
        "name": grant.client.name or "An assistant app",
        "created_at": grant.created_at.isoformat(),
        "last_used_at": grant.last_used_at.isoformat() if grant.last_used_at else None,
    }


def _connected_apps(user) -> list[dict]:
    from .models import ConnectorGrant

    rows = (
        ConnectorGrant.objects.select_related("client")
        .filter(user=user, refresh_digest__isnull=False)
        .order_by("-created_at")
    )
    return [_connected_app_out(g) for g in rows]


@api.get("/me/connected-apps", summary="Assistant apps connected to the rider's account")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def connected_apps_read(request):
    return _private(JsonResponse({"apps": _connected_apps(request.user)}))


@api.post("/me/connected-apps/{grant_id}/delete", summary="Disconnect one assistant app")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def connected_app_delete(request, grant_id: int):
    from .models import ConnectorGrant

    ConnectorGrant.objects.filter(user=request.user, pk=grant_id).delete()
    return _private(JsonResponse({"apps": _connected_apps(request.user)}))


# Saved-route versions (core.models.SavedRouteVersion): a save naming `version_of` replaces that
# route's line and inputs, keeping what it was as a version; restoring a version does the same
# with the version's. The owner's own: another account's route is "not found", as above.
VERSION_FIELDS = ("source", "line", "distance_m", "inputs", "answer", "gpx")


def _content_saved_at(row):
    """When the route's latest version was saved: when the one before it was replaced, or when
    the route was first saved."""
    last = row.versions.order_by("-replaced_at", "-pk").values_list("replaced_at", flat=True)
    return last.first() or row.created_at


def _version_size(fields: dict) -> int:
    """A version's bytes: its line, inputs and answer as JSON, and the file text it keeps."""
    held = (fields["line"], fields["inputs"], fields["answer"])
    return len(json.dumps(held, separators=(",", ":"))) + len(fields["gpx"].encode())


def _version_gpx(version) -> str:
    """A version's file text: its own, or (kept once) that of the first version after it that
    keeps one, else the route's."""
    if not version.gpx_same_as_next:
        return version.gpx
    later = (
        version.route.versions.filter(gpx_same_as_next=False, replaced_at__gt=version.replaced_at)
        .order_by("replaced_at", "pk")
        .values_list("gpx", flat=True)
        .first()
    )
    return version.route.gpx if later is None else later


def _replace_content(row, content: dict) -> None:
    """Keep the route as it is as a version, then make `content` the latest. Called in a
    transaction with the route's row locked."""
    from django.utils import timezone

    from .models import SavedRouteVersion, User

    # Taken in turn per account, so the account's byte cap is counted one save at a time.
    User.objects.select_for_update().filter(pk=row.user_id).first()
    kept = {f: getattr(row, f) for f in VERSION_FIELDS}
    # The same file as the content replacing it: kept once, by the newer one.
    same_file = bool(kept["gpx"]) and kept["gpx"] == content["gpx"]
    if same_file:
        kept["gpx"] = ""
    SavedRouteVersion.objects.create(
        route=row,
        saved_at=_content_saved_at(row),
        replaced_at=timezone.now(),
        gpx_same_as_next=same_file,
        size_bytes=_version_size(kept),
        **kept,
    )
    for f, value in content.items():
        setattr(row, f, value)
    row.save()
    # Past the caps the oldest go: per route, then across the account. Taking the oldest first
    # never strands a version that keeps its file in a later one.
    stale = list(
        row.versions.order_by("-replaced_at", "-pk").values_list("pk", flat=True)[
            SavedRouteVersion.MAX_PER_ROUTE :
        ]
    )
    SavedRouteVersion.objects.filter(pk__in=stale).delete()
    everything = SavedRouteVersion.objects.filter(route__user_id=row.user_id)
    total = sum(everything.values_list("size_bytes", flat=True))
    if total > SavedRouteVersion.MAX_BYTES_PER_ACCOUNT:
        drop = []
        for pk, size in everything.order_by("replaced_at", "pk").values_list("pk", "size_bytes"):
            if total <= SavedRouteVersion.MAX_BYTES_PER_ACCOUNT:
                break
            drop.append(pk)
            total -= size
        SavedRouteVersion.objects.filter(pk__in=drop).delete()


def _same_content(row, content: dict) -> bool:
    # The answer is the planner's words about the same line and inputs; it does not decide.
    return all(getattr(row, f) == content[f] for f in VERSION_FIELDS if f != "answer")


def _locked_route(request, route_id: int):
    from .models import SavedRoute

    return SavedRoute.objects.select_for_update().filter(user=request.user, pk=route_id).first()


def _save_version(request, route_id: int, name: str, content: dict):
    from django.db import transaction

    with transaction.atomic():
        row = _locked_route(request, route_id)
        if row is None:
            return _stress_error(404, "That saved route is not in your account.", code="not_found")
        changed = not _same_content(row, content)
        if changed:
            _replace_content(row, content)
        if row.name != name:
            row.name = name
            row.save(update_fields=["name", "updated_at"])
    if changed:
        from . import saved_route_alerts

        saved_route_alerts.check(row)  # a new line: its closures and box again
    return _private(JsonResponse({**_route_summary(row), "versioned": changed}))


@api.get("/me/routes/{route_id}/versions", summary="A saved route's versions, newest first")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def saved_route_versions(request, route_id: int):
    from . import accounts
    from .models import SavedRouteVersion

    row = _saved_route(request, route_id)
    if row is None:
        return _stress_error(404, "That saved route is not in your account.", code="not_found")
    kept = list(
        row.versions.order_by("-replaced_at", "-pk").values(
            "id", "saved_at", "distance_m", "source", "inputs"
        )
    )
    latest = {
        "id": None,
        "saved_at": _content_saved_at(row),
        "distance_m": row.distance_m,
        "source": row.source,
        "inputs": row.inputs,
    }
    entries = [latest, *kept]
    out = []
    for i, entry in enumerate(entries):
        if i + 1 < len(entries):
            change = accounts.change_phrase(entries[i + 1], entry)
        else:
            # The oldest kept: the first save, unless older versions went past the cap.
            change = "First saved" if entry["saved_at"] == row.created_at else ""
        out.append(
            {
                "id": entry["id"],
                "saved_at": entry["saved_at"].isoformat(),
                "distance_m": entry["distance_m"],
                "source": entry["source"],
                "change": change,
            }
        )
    return _private(JsonResponse({"versions": out, "max": SavedRouteVersion.MAX_PER_ROUTE}))


@api.post(
    "/me/routes/{route_id}/versions/{version_id}/restore",
    summary="Make an earlier version of a saved route its latest again",
)
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def saved_route_restore(request, route_id: int, version_id: int):
    from django.db import transaction

    with transaction.atomic():
        row = _locked_route(request, route_id)
        version = row.versions.filter(pk=version_id).first() if row is not None else None
        if version is None:
            return _stress_error(404, "That version is not in your account.", code="not_found")
        content = {f: getattr(version, f) for f in VERSION_FIELDS}
        content["gpx"] = _version_gpx(version)
        # Restoring makes a new latest version: the one it replaces stays in the list.
        changed = not _same_content(row, content)
        if changed:
            _replace_content(row, content)
    if changed:
        from . import saved_route_alerts

        saved_route_alerts.check(row)  # a new line: its closures and box again
    return _private(JsonResponse(_route_full(row)))


@api.get("/me/routes/{route_id}", summary="One saved route, with its line, inputs and answer")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def saved_route_read(request, route_id: int):
    row = _saved_route(request, route_id)
    if row is None:
        return _stress_error(404, "That saved route is not in your account.", code="not_found")
    return _private(JsonResponse(_route_full(row)))


@api.patch("/me/routes/{route_id}", summary="Rename a saved route")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def saved_route_rename(request, route_id: int):
    from . import accounts

    body, refusal = _json_body(request, MAX_BODY_BYTES)
    if refusal is not None:
        return refusal
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > accounts.NAME_MAX:
        return _stress_error(
            400, f"Give the route a name of up to {accounts.NAME_MAX} characters.", field="name"
        )
    row = _saved_route(request, route_id)
    if row is None:
        return _stress_error(404, "That saved route is not in your account.", code="not_found")
    row.name = name.strip()
    row.save(update_fields=["name", "updated_at"])
    return _private(JsonResponse(_route_summary(row)))


@api.delete("/me/routes/{route_id}", summary="Delete a saved route")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def saved_route_delete(request, route_id: int):
    row = _saved_route(request, route_id)
    if row is None:
        return _stress_error(404, "That saved route is not in your account.", code="not_found")
    row.delete()
    return _private(JsonResponse({"deleted": route_id}))


# Shared routes (v0.7.0, "share the identical route"; core.shared_routes, core.models.SharedRoute):
# the Share button keeps the exact line under a 128-bit id the page made, and the link it shares
# opens that line unchanged. Signed out or in; nothing of the sharer is kept. Kept a year after
# it was last opened (or permanently, or until a date, as the sharer chose); the expired go at
# every share and open.


# The longest single string a kept answer may hold: the planner's own words (a turn, a notice,
# an attribution) are a sentence or two; nothing it writes comes near this.
ANSWER_STRING_MAX = 2000


def _longest_string(value) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return max((max(len(k), _longest_string(v)) for k, v in value.items()), default=0)
    if isinstance(value, list):
        return max((_longest_string(v) for v in value), default=0)
    return 0


def _clean_answer(answer) -> tuple[dict | None, str | None]:
    """A kept route's answer as the planner's own (`RouteOut`), or (None, why not). A saved or
    shared answer is served back as planner output, so it is read through the same schema the
    planner answers with: keys it does not name are dropped, a malformed one is refused, and no
    string in it is longer than `ANSWER_STRING_MAX`."""
    import pydantic

    try:
        model = RouteOut.model_validate(answer)
    except pydantic.ValidationError:
        return None, "The route's answer is not one this planner gives."
    out = model.model_dump(mode="json", by_alias=True)
    if _longest_string(out) > ANSWER_STRING_MAX:
        return None, "The route's answer holds text longer than this planner writes."
    return out, None


def _shared_out(row) -> dict:
    return {
        "id": row.pk,
        "name": row.name,
        "source": row.source,
        "distance_m": row.distance_m,
        "line": row.line,
        "inputs": row.inputs,
        "answer": row.answer,
        "gpx": row.gpx,
        "created_at": row.created_at.isoformat(),
        "keep": row.keep,
        "delete_after": row.delete_after.isoformat() if row.delete_after else None,
    }


def _purge_shared(now) -> None:
    from . import shared_routes

    shared_routes.prune(now)


@api.post("/shared-routes", summary="Keep a shared route's exact line under the link's id")
@decorate_view(
    same_site_only,
    ratelimit.rate_limited(ratelimit.SHARED_ROUTE_WRITES),
    errors_as_json,
)
def shared_route_add(request):
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from . import shared_routes
    from .models import SharedRoute

    body, refusal = _json_body(request, shared_routes.MAX_BYTES)
    if refusal is not None:
        return refusal
    problem = shared_routes.body_problem(body)
    if problem:
        return _stress_error(400, problem[0], field=problem[1])
    answer = body.get("answer")
    if answer is not None:
        answer, problem = _clean_answer(answer)
        if problem:
            return _stress_error(400, problem, field="answer")
    now = timezone.now()
    _purge_shared(now)
    keep = body.get("keep", "year")
    delete_after = (
        shared_routes.delete_after_of(body.get("delete_after"), timezone.localdate(now))
        if keep == "until"
        else None
    )
    from . import share_preview

    try:
        with transaction.atomic():
            row = SharedRoute(
                id=body["id"],
                name=(body.get("name") or "").strip() or shared_routes.DEFAULT_NAME,
                source=body.get("source", "plan"),
                line=body["line"],
                distance_m=float(body["distance_m"]),
                inputs=body.get("inputs", {}),
                answer=shared_routes.public_answer(answer) if answer is not None else None,
                gpx=body.get("gpx", "") or "",
                created_at=now,
                last_opened_at=now,
                keep=keep,
                delete_after=delete_after,
                # Signed in, the owner, so only they can turn the link off (nothing else of them).
                owner=request.user if signed_in(request) else None,
                # Missing (a page from before previews) is no image: it never said where Home is.
                preview_image=body.get("preview_image", False),
            )
            # Home's circle as it is now, kept where the route starts, ends or stops in it.
            share_preview.freeze_zone(row)
            row.save(force_insert=True)
    except IntegrityError:
        # Ids are 128 random bits: a taken one is a resend, never another rider's to replace.
        return _stress_error(409, "That link's route is already kept.", code="taken")
    response = JsonResponse({"id": row.pk}, status=201)
    response["Cache-Control"] = "no-store"
    return response


@api.get("/shared-routes/{route_id}", summary="A shared route's exact line, as it was shared")
@decorate_view(
    same_site_only,
    ratelimit.rate_limited(ratelimit.SHARED_ROUTE_READS),
    errors_as_json,
)
def shared_route_read(request, route_id: str):
    from django.utils import timezone

    from . import shared_routes
    from .models import SharedRoute

    gone = _stress_error(
        404, "That shared route is no longer kept; its link plans it again.", code="not_found"
    )
    if not shared_routes.id_ok(route_id):
        return gone
    row = SharedRoute.objects.filter(pk=route_id).first()
    now = timezone.now()
    if row is None or shared_routes.expired(row, now):
        _purge_shared(now)
        return gone
    if row.revoked_at is not None:
        # Turned off by its owner: the page says so and plans nothing (core.shared_routes.REVOKED).
        response = _stress_error(410, shared_routes.REVOKED, code="revoked")
        response["Cache-Control"] = "no-store"
        return response
    # A year's keeping counts from the last open; written at most once a day.
    if row.last_opened_at < now - shared_routes.TOUCH_EVERY:
        SharedRoute.objects.filter(pk=row.pk).update(last_opened_at=now)
    response = JsonResponse(_shared_out(row))
    response["Cache-Control"] = "no-store"
    return response


# A signed-in sharer's own shared links (My routes in Plan): listed, turned off, or swapped for a
# new link. Another account's link is "not found", as a saved route is.


def _owned_shared(request, route_id: str):
    from . import shared_routes
    from .models import SharedRoute

    if not shared_routes.id_ok(route_id):
        return None
    return SharedRoute.objects.filter(
        owner=request.user, pk=route_id, revoked_at__isnull=True
    ).first()


def _shared_summary(request, row) -> dict:
    from . import shared_routes

    return {
        "id": row.pk,
        "name": row.name,
        "source": row.source,
        "distance_m": row.distance_m,
        "created_at": row.created_at.isoformat(),
        "keep": row.keep,
        "delete_after": row.delete_after.isoformat() if row.delete_after else None,
        "link": shared_routes.link_of(row, f"{request.scheme}://{request.get_host()}"),
    }


SHARED_NOT_YOURS = "That shared link is not one of yours."


@api.get("/me/shared-routes", summary="The signed-in rider's shared links still working")
@decorate_view(
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.ME),
    errors_as_json,
)
def my_shared_routes(request):
    from django.middleware.csrf import get_token
    from django.utils import timezone

    from . import shared_routes
    from .models import SharedRoute

    get_token(request)
    now = timezone.now()
    rows = SharedRoute.objects.filter(owner=request.user, revoked_at__isnull=True).order_by(
        "-created_at", "pk"
    )
    links = [
        _shared_summary(request, r)
        for r in rows.defer("line", "answer", "gpx", "preview_png")
        if not shared_routes.expired(r, now)
    ]
    return _private(JsonResponse({"links": links}))


@api.post("/me/shared-routes/{route_id}/revoke", summary="Turn off one of your shared links")
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def my_shared_route_revoke(request, route_id: str):
    from django.utils import timezone

    from . import shared_routes

    row = _owned_shared(request, route_id)
    if row is None:
        return _stress_error(404, SHARED_NOT_YOURS, code="not_found")
    shared_routes.revoke(row, timezone.now())
    return _private(JsonResponse({"revoked": route_id}))


@api.post(
    "/me/shared-routes/{route_id}/regenerate",
    summary="A new link for one of your shared routes; the old link is turned off",
)
@decorate_view(
    ratelimit.user_rate_limited(ratelimit.ACCOUNT_WRITES),
    csrf_protected,
    signed_in_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    # A new link is a new shared route: counted with Share's.
    ratelimit.rate_limited(ratelimit.SHARED_ROUTE_WRITES),
    errors_as_json,
)
def my_shared_route_regenerate(request, route_id: str):
    from django.utils import timezone

    from . import shared_routes

    now = timezone.now()
    row = _owned_shared(request, route_id)
    if row is None or shared_routes.expired(row, now):
        return _stress_error(404, SHARED_NOT_YOURS, code="not_found")
    fresh = shared_routes.regenerate(row, now)
    return _private(JsonResponse(_shared_summary(request, fresh), status=201))


# The closures a kept line runs along now (v0.7.0 plan, "GPX export as close to identical as
# possible, closure warning first", with its correction: mainly when a kept route is opened or
# ridden). Public, like planning; the line is only measured, never kept.
class AreaClosuresIn(Schema):
    bbox: str = Field(
        max_length=120,
        description="The map's view: west,south,east,north in degrees, at most 0.4 by 0.3.",
    )
    permits: bool = Field(
        default=False,
        description="Also DDOT's permits (Plan's DC permits switch); off by default.",
    )


class AreaClosuresOut(Schema):
    closures: list[ClosureOut]


# GET /api/closures/map?bbox=west,south,east,north (v0.12.0): the closures in force now in the
# map's view, drawn with no route as with one (core.workzones.area_rows). A GET of a map view,
# as a tile is: no point of the rider's is in it.
@api.get(
    "/closures/map",
    response={200: AreaClosuresOut, 400: ErrorOut, 429: ErrorOut, 500: ErrorOut},
    summary="The closures and construction in force now in a map view",
)
@decorate_view(ratelimit.rate_limited(ratelimit.CLOSURES_MAP), errors_as_json)
def closures_map(request, params: Query[AreaClosuresIn], response: HttpResponse):
    from . import workzones as work_zones

    response["Cache-Control"] = "no-store"
    try:
        box = work_zones.parse_area(params.bbox)
    except ValueError as error:
        return Status(400, {"error": str(error)})
    return Status(200, {"closures": work_zones.area_rows(box, permits=params.permits)})


CLOSURE_LINE_MAX_POINTS = 10_000
CLOSURE_BODY_MAX_BYTES = 512 * 1024
CLOSURE_BYPASS_MAX = 50


@api.post("/closures/check", summary="The closures in force now that a route's line runs along")
@decorate_view(
    same_site_only,
    ratelimit.rate_limited(ratelimit.CLOSURE_CHECK),
    errors_as_json,
)
def closures_check(request):
    from . import accounts
    from . import workzones as work_zones

    body, refusal = _json_body(request, CLOSURE_BODY_MAX_BYTES)
    if refusal is not None:
        return refusal
    line = body.get("line") if isinstance(body, dict) else None
    problem = accounts.line_problem(line)
    if problem is None and len(line) > CLOSURE_LINE_MAX_POINTS:
        problem = f"Send at most {CLOSURE_LINE_MAX_POINTS:,} points; thin the line first."
    # Additive (v0.7.0, "DC closures source"): the plan's ride-time dial, so a closure is
    # matched at the ride, not today; and the closures the rider chose to route through.
    extra = body if isinstance(body, dict) else {}
    when = extra.get("when")
    if problem is None and when is not None and when not in ridetime.WHENS:
        problem = f"when is one of {', '.join(ridetime.WHENS)}."
    bypass = extra.get("bypass") or []
    if problem is None and (
        not isinstance(bypass, list)
        or len(bypass) > CLOSURE_BYPASS_MAX
        or not all(isinstance(b, str) and 0 < len(b) <= 200 for b in bypass)
    ):
        problem = f"bypass is a list of at most {CLOSURE_BYPASS_MAX} closure ids."
    # v0.9.1, Go and a ride: only the closures known to be on, not DDOT's permits.
    now_only = extra.get("now_only", False)
    if problem is None and not isinstance(now_only, bool):
        problem = "now_only is true or false."
    if problem:
        return _error(400, problem)
    return JsonResponse(work_zones.closures_on(line, when=when, bypass=bypass, now_only=now_only))


WEATHER_BODY_MAX_BYTES = 4096


@api.post("/weather/check", summary="NWS alerts and rain forecast along the line still to ride")
@decorate_view(
    same_site_only,
    ratelimit.rate_limited(ratelimit.WEATHER_CHECK),
    errors_as_json,
)
def weather_check(request):
    """Stephen 2026-10-24 (core.weather): a few points along the line still to ride, each with
    the seconds until the rider gets there; the NWS alerts in force there during the ride and
    the first point where rain is forecast. The points are rounded, never logged or kept."""
    from . import weather

    body, refusal = _json_body(request, WEATHER_BODY_MAX_BYTES)
    if refusal is not None:
        return refusal
    points = body.get("points") if isinstance(body, dict) else None
    problem = weather.points_problem(points)
    if problem:
        return _error(400, problem)
    out = JsonResponse(weather.shared().check([tuple(p) for p in points]))
    out["Cache-Control"] = "no-store"
    return out


# Ride mode's 311 (v0.7.0 "Go riding fixes" item 3; core.dc311): whether the server sends a
# report to DC 311 itself (only with DC311_API_KEY set), and the sending. Off, the page opens
# the phone's text app to 311 instead. The position and the words go to DC only, never a log.
REPORT_311_BODY_MAX_BYTES = 2048


@api.get("/report311", summary="Whether Ride mode's 311 reports are sent to DC from here")
@decorate_view(
    ratelimit.rate_limited(ratelimit.REPORT_311_STATUS),
    same_site_only,
    errors_as_json,
)
def report311_status(request):
    from . import dc311

    on = dc311.enabled()
    # On, the answer carries a short-lived signed ticket that a send must bring back.
    response = JsonResponse(
        {"enabled": True, "ticket": dc311.ticket()} if on else {"enabled": False}
    )
    response["Cache-Control"] = "no-store"
    return response


@api.get("/report311/where", summary="Which 311 website takes a problem at a point")
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.GEOCODE_IN_FLIGHT, ratelimit.name_slots),
    ratelimit.rate_limited(ratelimit.REVERSE),
    ratelimit.rate_limited(ratelimit.REVERSE_BURST),
    same_site_only,
    errors_as_json,
)
def report311_where(request, params: Query[ReverseIn]):
    """The 311 log's site for an entry (core.report_log.where): an id the page knows, or null
    where the point is in no jurisdiction the log names. The point is not kept."""
    from . import report_log

    try:
        found = report_log.where(params.lat, params.lon, lang=params.lang)
    except geocode.Unavailable as unavailable:
        logger.warning("311 log: the geocoder did not answer: %s", unavailable)
        out = JsonResponse({"error": GEOCODER_DOWN}, status=502)
        out["Cache-Control"] = "no-store"
        return out
    out = JsonResponse({"where": found})
    out["Cache-Control"] = "private, max-age=86400"
    return out


@api.post("/report311", summary="Send one Ride mode report to DC 311 (only with a DC key)")
@decorate_view(
    same_site_only,
    ratelimit.rate_limited(ratelimit.REPORT_311),
    errors_as_json,
)
def report311_send(request):
    from . import dc311

    body, refusal = _json_body(request, REPORT_311_BODY_MAX_BYTES)
    if refusal is not None:
        return refusal
    body = body if isinstance(body, dict) else {}
    kind, lat, lon = body.get("kind"), body.get("lat"), body.get("lon")
    description = body.get("description", "")
    if kind not in dc311.KINDS:
        return _error(400, f"kind is one of {', '.join(dc311.KINDS)}.")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
        return _error(400, "lat and lon are numbers.")
    if not isinstance(description, str) or len(description) > dc311.DESCRIPTION_MAX:
        return _error(400, f"description is text of at most {dc311.DESCRIPTION_MAX} characters.")
    if dc311.enabled():
        if not dc311.ticket_ok(body.get("ticket")):
            out = JsonResponse(
                {"error": "Ask the server again, then send the report.", "code": "no_ticket"},
                status=403,
            )
            out["Cache-Control"] = "no-store"
            return out
        everyone = ratelimit.Limit(
            scope=dc311.GLOBAL_SCOPE, requests=dc311.HOURLY_MAX, window_s=3600
        )
        if not ratelimit.hit(everyone, "all").allowed:
            out = JsonResponse(
                {"error": "DC 311 reports from here are paused for now.", "code": "busy"},
                status=429,
            )
            out["Cache-Control"] = "no-store"
            return out
    try:
        ident = dc311.send(kind, float(lat), float(lon), description)
    except dc311.NotSent as refused:
        out = JsonResponse({"error": refused.message, "code": refused.code}, status=refused.status)
        out["Cache-Control"] = "no-store"
        return out
    out = JsonResponse({"sent": True, "id": ident})
    out["Cache-Control"] = "no-store"
    return out


# Mass Ride and Group Ride links: the other riders as dots, and alerts (v0.7.0 plan;
# core.ride_presence). No sign-in: a ride is the digest of the link's plan and a rider a random
# per-ride token. Positions are in POST bodies only, kept in memory for 2 minutes, never logged.
# The fine limits are per token, in memory; the database counts only a generous ceiling per
# address (a whole ride's phones can share one carrier address) and per ride, by keyed digest.


def ride_writes_limited(view):
    """Count a write against its ride (ratelimit.RIDE_WRITES), keyed by a digest of the ride id;
    a path that is not a ride id is left to the view's 404 uncounted."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        from . import ride_presence

        ride_id = str(kwargs.get("ride_id", ""))
        if ride_presence.RIDE_ID.match(ride_id):
            limit = ratelimit.RIDE_WRITES
            decision = ratelimit.hit(limit, ratelimit.client_key(f"ride:{ride_id}"))
            if not decision.allowed:
                out = _stress_error(429, "This ride is busy; try again shortly.")
                out["Retry-After"] = str(decision.retry_after_s)
                return out
        return view(request, *args, **kwargs)

    return wrapped


# decorate_view wraps in order, so the last is outermost: a foreign page is refused before it
# is counted, and a write is counted against its address before its ride.
RIDE_READ_GUARDS = (ratelimit.rate_limited(ratelimit.RIDE_LINKS), same_site_editor, errors_as_json)
RIDE_WRITE_GUARDS = (
    ride_writes_limited,
    ratelimit.rate_limited(ratelimit.RIDE_LINKS),
    same_site_editor,
    errors_as_json,
)


def _ride_call(request, fn):
    from . import ride_presence

    try:
        answer = fn(ride_presence)
    except ride_presence.Refused as refused:
        out = _stress_error(refused.status, refused.message)
        if refused.retry_after_s:
            out["Retry-After"] = str(refused.retry_after_s)
        return out
    return _private(JsonResponse(answer or {"ok": True}))


def _ride_body(request):
    body, refusal = _json_body(request, 2048)
    if refusal is None and not isinstance(body, dict):
        refusal = _stress_error(400, "Send an object.")
    return body, refusal


@api.get("/rides/{ride_id}", summary="The other riders' dots on a ride link, and its alerts")
@decorate_view(*RIDE_READ_GUARDS)
def ride_read(request, ride_id: str):
    token = request.META.get("HTTP_X_RIDE_TOKEN", "")
    # A broadcast link's leader key (core.ride_presence.leader_key): marks the sharer's dot.
    leader = request.META.get("HTTP_X_RIDE_LEADER", "")
    return _ride_call(request, lambda rp: rp.read(ride_id, token, leader=leader))


@api.post("/rides/{ride_id}/here", summary="Show this rider as a dot (rounded to 20 m) for 2 min")
@decorate_view(*RIDE_WRITE_GUARDS)
def ride_here(request, ride_id: str):
    body, refusal = _ride_body(request)
    if refusal is not None:
        return refusal
    return _ride_call(
        request,
        lambda rp: rp.post_position(
            ride_id, body.get("token", ""), body.get("lon"), body.get("lat"), body.get("role")
        ),
    )


@api.post(
    "/rides/{ride_id}/path",
    summary="A broadcast leader's route and ridden path, kept in memory for 2 min",
)
@decorate_view(*RIDE_WRITE_GUARDS)
def ride_path(request, ride_id: str):
    from . import ride_presence

    body, refusal = _json_body(request, ride_presence.PATH_BODY_BYTES)
    if refusal is None and not isinstance(body, dict):
        refusal = _stress_error(400, "Send an object.")
    if refusal is not None:
        return refusal
    return _ride_call(
        request,
        lambda rp: rp.post_path(
            ride_id, body.get("token", ""), body.get("route"), body.get("trail")
        ),
    )


@api.post("/rides/{ride_id}/leave", summary="Stop showing this rider's dot at once")
@decorate_view(*RIDE_WRITE_GUARDS)
def ride_leave(request, ride_id: str):
    body, refusal = _ride_body(request)
    if refusal is not None:
        return refusal
    return _ride_call(request, lambda rp: rp.leave(ride_id, body.get("token", "")))


@api.post("/rides/{ride_id}/alerts", summary="Send an alert to everyone on the ride link")
@decorate_view(*RIDE_WRITE_GUARDS)
def ride_alert(request, ride_id: str):
    body, refusal = _ride_body(request)
    if refusal is not None:
        return refusal
    return _ride_call(
        request,
        lambda rp: rp.send_alert(
            ride_id,
            body.get("token", ""),
            str(body.get("ride_type", "")),
            str(body.get("kind", "")),
            str(body.get("text", "") or ""),
            body.get("lon"),
            body.get("lat"),
        ),
    )


@api.post("/rides/{ride_id}/alerts/{alert_id}/clear", summary="Clear an alert you sent")
@decorate_view(*RIDE_WRITE_GUARDS)
def ride_alert_clear(request, ride_id: str, alert_id: str):
    body, refusal = _ride_body(request)
    if refusal is not None:
        return refusal
    return _ride_call(
        request, lambda rp: rp.clear_alert(ride_id, body.get("token", ""), alert_id[:32])
    )


class StepOut(Schema):
    value: float = Field(description="1 to 5 by halves (1.5 is a half step; 5 is Avoid).")
    words: str


class CategoryOut(Schema):
    id: str
    label: str


class CurrentOut(Schema):
    step: float = Field(description="The road's level now, half steps included.")
    words: str
    source: Literal["classifier", "file", "admin", "panel"]
    at_least: bool
    category: str | None = None
    public_note: str | None = None
    display: str | None = None
    private_reason: str | None = Field(
        default=None, description="For the admin only; never shown to a rider."
    )
    when: str | None = None
    by: Literal["you", "another admin"] | None = None


class RecentEditOut(Schema):
    id: int
    action: str
    at: str
    can_undo: bool


class StretchOut(Schema):
    name: str
    osm_way_ids: list[int] = Field(description="Send these as osm_way_ids to change them all.")
    pieces: int
    length_m: float
    capped: bool = Field(description="True where the stretch goes on past the most one edit takes.")
    expected: str = Field(description="The stretch's own token, sent back with a stretch edit.")


class StretchStateOut(Schema):
    stretch: StretchOut | None = Field(
        default=None,
        description="The named stretch the road piece is in, or null where it is the only piece.",
    )


class EditorStateOut(Schema):
    osm_way_id: int
    classifier_step: int | None = Field(
        default=None, description="Null when an earlier override hides it."
    )
    can_raise_only: bool
    current: CurrentOut
    expected: str = Field(description="Send back unchanged with the edit; a mismatch is a 409.")
    steps: list[StepOut]
    categories: list[CategoryOut]
    reason_max: int
    note_max: int
    recent_edit: RecentEditOut | None = None
    pieces: int
    half_steps: bool = Field(
        default=True,
        description="False until the live table can hold a half step (the next data update).",
    )


@api.get(
    "/stress-edits/way/{osm_way_id}",
    response={
        200: EditorStateOut,
        401: StressEditErrorOut,
        403: StressEditErrorOut,
        404: StressEditErrorOut,
        429: ErrorOut,
        500: ErrorOut,
    },
    summary="The stress editor's starting state for one way (instance admin)",
)
@decorate_view(
    instance_admin_only(audited=False),
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def stress_edit_state(request, osm_way_id: int, response: HttpResponse):
    from django.middleware.csrf import get_token

    from . import stress_edits

    get_token(request)
    try:
        state = stress_edits.editor_state(request.user, osm_way_id)
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    _private(response)
    return Status(200, state)


@api.get(
    "/stress-edits/way/{osm_way_id}/stretch",
    response={
        200: StretchStateOut,
        401: StressEditErrorOut,
        403: StressEditErrorOut,
        404: StressEditErrorOut,
        429: ErrorOut,
        500: ErrorOut,
    },
    summary="The named stretch a road piece is in, for the editor's extent choice (instance admin)",
)
@decorate_view(
    instance_admin_only(audited=False),
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def stress_edit_stretch(request, osm_way_id: int, response: HttpResponse):
    from . import stress_edits

    try:
        stretch = stress_edits.stretch_state(osm_way_id)
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    _private(response)
    return Status(200, {"stretch": stretch})


class StressEditIn(Schema):
    model_config = ConfigDict(extra="forbid")

    osm_way_ids: list[StrictInt] = Field(
        min_length=1,
        max_length=40,
        description="One road piece, or a named stretch's pieces (the editor state's stretch).",
    )
    step: StrictFloat = Field(
        description="The level, 1 to 5 by halves (1.5, 2.5, 3.5, 4.5 are half steps; 5 is Avoid)."
    )
    at_least: StrictBool = Field(
        default=False, description="Only raise it: keep the current level where it is higher."
    )
    category: str = Field(max_length=40, description="Why, in a category the panel can show.")
    reason: str = Field(
        max_length=2000, description="Private. Required, at most 500 characters; never shown."
    )
    public_note: str | None = Field(
        default=None, max_length=1000, description="Optional note riders may read."
    )
    display: Literal["route_only", "map"] = "route_only"
    expected: str = Field(max_length=64)


class EditedWayOut(Schema):
    osm_way_id: int
    step: float
    changed: bool = Field(
        description="False where the road already had this level (or met the floor)."
    )


class StressEditOut(Schema):
    edit_id: int
    ways: list[EditedWayOut]
    generation: int = Field(description="Added to the stress tile URLs as ?rev= by the editor.")
    undo_until: str = Field(description="When the Undo stops being offered, ISO 8601.")


STRESS_EDIT_RESPONSES = {
    200: StressEditOut,
    400: StressEditErrorOut,
    401: StressEditErrorOut,
    403: StressEditErrorOut,
    404: StressEditErrorOut,
    409: StressEditErrorOut,
    429: ErrorOut,
    500: ErrorOut,
}


def _edit_out(result) -> dict:
    from . import stress_edits

    return {
        "edit_id": result.edit.pk,
        "ways": result.ways,
        "generation": result.generation,
        "undo_until": (result.edit.at + stress_edits.UNDO_WINDOW).isoformat(),
    }


def _edit_refusal(request, refused) -> JsonResponse:
    if refused.status == 409:
        _refused(request, request.user, f"{refused.code}: {refused.message}")
    return _stress_error(refused.status, refused.message, refused.field, refused.code)


# Ninja wraps these innermost first, so the order written is the reverse of the order they
# run in: the error guard, the address count, the same-site check, the JSON body, the
# account (401, 403), the CSRF token, then the account's own count.
STRESS_WRITE = (
    ratelimit.user_rate_limited(ratelimit.STRESS_EDIT_WRITES),
    csrf_protected,
    instance_admin_only(audited=True),
    json_body_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)


@api.post(
    "/stress-edits",
    response=STRESS_EDIT_RESPONSES,
    summary="Change a road's traffic stress at once (instance admin)",
)
@decorate_view(*STRESS_WRITE)
def stress_edit_create(request, body: StressEditIn, response: HttpResponse):
    from . import stress_edits

    try:
        tier, half = stress_edits.split_step(body.step)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    spec = stress_edits.Spec(
        tier=tier,
        half=half,
        at_least=body.at_least,
        category=body.category,
        reason=body.reason,
        public_note=body.public_note.strip() if body.public_note else None,
        display=body.display,
    )
    try:
        result = stress_edits.apply(request.user, body.osm_way_ids, spec, body.expected)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(200, _edit_out(result))


class SurfaceEditIn(Schema):
    model_config = ConfigDict(extra="forbid")

    osm_way_ids: list[StrictInt] = Field(
        min_length=1, max_length=40, description="One road piece, or a named stretch's pieces."
    )
    surface: Literal["rough", "gravel", "sand", "dirt"] | None = Field(
        description="The surface routes should price it as; null takes the penalty off."
    )
    reason: str = Field(
        max_length=2000, description="Private. Required, at most 500 characters; never shown."
    )


class SurfaceEditOut(Schema):
    changed: list[int] = Field(description="The ways whose penalty changed (the rest had it).")
    message: str


@api.post(
    "/stress-edits/surface",
    response={**STRESS_EDIT_RESPONSES, 200: SurfaceEditOut},
    summary="Set a road's surface penalty, for the next map rebuild (instance admin)",
)
@decorate_view(*STRESS_WRITE)
def stress_edit_surface(request, body: SurfaceEditIn, response: HttpResponse):
    from . import stress_edits

    try:
        rows = stress_edits.set_surface(request.user, body.osm_way_ids, body.surface, body.reason)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    what = "taken off" if body.surface is None else "set"
    return Status(
        200,
        {
            "changed": [row.osm_way_id for row in rows],
            "message": (
                f"Surface penalty {what}. It applies at the next map rebuild."
                if rows
                else "Nothing changed: the road already had that."
            ),
        },
    )


class UndoIn(Schema):
    model_config = ConfigDict(extra="forbid")


@api.post(
    "/stress-edits/{edit_id}/undo",
    response=STRESS_EDIT_RESPONSES,
    summary="Undo a change within 30 minutes (instance admin)",
)
@decorate_view(*STRESS_WRITE)
def stress_edit_undo(request, edit_id: int, body: UndoIn, response: HttpResponse):
    from . import stress_edits

    try:
        result = stress_edits.undo(request.user, edit_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(200, _edit_out(result))


# ---- Rider suggestions (441h, 460.4, 460.5; core.suggestions) ----


def suggester_only(view):
    """A session of an account the suggestion setting allows, or 401 / 403 (audited)."""
    from . import suggestions

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not signed_in(request):
            return _stress_error(401, "Sign in to suggest a change.", code="signed_out")
        if not suggestions.may_suggest(request.user):
            _refused(request, request.user, "may not suggest")
            return _stress_error(
                403, "Suggestions are not open to your account.", code="not_allowed"
            )
        return view(request, *args, **kwargs)

    return wrapped


class SuggestionIn(Schema):
    model_config = ConfigDict(extra="forbid")

    osm_way_id: StrictInt
    lat: StrictFloat = Field(ge=-90, le=90, description="The spot the rider asked about.")
    lon: StrictFloat = Field(ge=-180, le=180)
    step: StrictFloat = Field(description="The suggested level, 1 to 5 by halves.")
    reason: str = Field(max_length=2000, description="Required, at most 500 characters.")


class SuggestionCreatedOut(Schema):
    id: int
    message: str


class ReviewNoteOut(Schema):
    agree: bool
    reason: str


class ReviewTalliesOut(Schema):
    agree: int
    disagree: int
    mine: Literal["agree", "disagree"] | None = Field(
        default=None, description="Your own mark on it, if any."
    )
    notes: list[ReviewNoteOut] = Field(
        default_factory=list, description="The one-line reasons given, oldest first, unnamed."
    )


class SuggestionOut(Schema):
    id: int
    osm_way_id: int
    road: str
    lat: float
    lon: float
    current_step: float
    current_words: str
    step: float
    words: str
    reason: str
    signed_out: bool = Field(
        default=False, description="Sent from the short form by someone not signed in (v0.7.0)."
    )
    reasons: list[str] = Field(default_factory=list, description="The one-tap reasons' keys.")
    agree: int = Field(
        default=1, description="Open sends for the road that agree with it, itself included."
    )
    reviews: ReviewTalliesOut | None = Field(
        default=None, description="Second reviewers' agree and disagree marks (v0.7.0)."
    )
    status: Literal["pending", "sent_to_discord"]
    created_at: str
    sent_at: str | None = None


class SuggestionListOut(Schema):
    suggestions: list[SuggestionOut]


class SuggestionDoneOut(Schema):
    id: int
    status: str
    message: str
    generation: int | None = None


class PollOptionOut(Schema):
    letter: str
    label: str
    tier: int | None = Field(description="The level a vote for it means; null for Not sure.")


class DiscordPostOut(Schema):
    id: int
    status: str
    post: str = Field(description="Ready to paste: at most 2,000 characters, no mentions.")
    characters: int
    options: list[PollOptionOut]


SUGGESTION_RESPONSES = {
    400: StressEditErrorOut,
    401: StressEditErrorOut,
    403: StressEditErrorOut,
    404: StressEditErrorOut,
    409: StressEditErrorOut,
    429: ErrorOut,
    500: ErrorOut,
}

# The review's three actions: the editor's guards with a count of their own (a larger one), so a
# long review does not use up the admin's editing budget.
REVIEW_WRITE = (
    ratelimit.user_rate_limited(ratelimit.SUGGEST_REVIEW_WRITES),
    *STRESS_WRITE[1:],
)

SUGGEST_WRITE = (
    ratelimit.user_rate_limited(ratelimit.SUGGEST_WRITES),
    csrf_protected,
    suggester_only,
    json_body_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)


@api.post(
    "/stress-suggestions",
    response={200: SuggestionCreatedOut, **SUGGESTION_RESPONSES},
    summary="Suggest a road's traffic stress level (a rider the settings allow)",
)
@decorate_view(*SUGGEST_WRITE)
def stress_suggestion_create(request, body: SuggestionIn, response: HttpResponse):
    from . import stress_edits, suggestions

    try:
        suggestion = suggestions.create(
            request.user, body.osm_way_id, body.lat, body.lon, body.step, body.reason
        )
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    _private(response)
    return Status(
        200,
        {
            "id": suggestion.pk,
            "message": "Thanks. Your suggestion was sent to the map's admins. "
            "Nothing changes on the map until one of them reviews it.",
        },
    )


# ---- Signed-out suggestions (v0.7.0; core.signed_out_suggestions) ----
#
# GET /api/stress-suggestions/ticket?way=: the short form's ticket, asked when it opens on a road
# (proof the send came from an opened panel), and the CSRF cookie the send carries back.
# POST /api/stress-suggestions/signed-out: the send. No account, address or device is stored.


class SuggestTicketIn(Schema):
    # At most a Postgres bigint: a larger id is a 400 here, not the database's overflow (a 500).
    way: int = Field(ge=1, le=2**63 - 1, description="The road's OSM way id.")


class SuggestTicketOut(Schema):
    ticket: str
    reasons: list[list[str]] = Field(description="The one-tap reasons: [key, words], in order.")


class SignedOutSuggestionIn(Schema):
    model_config = ConfigDict(extra="forbid")

    osm_way_id: StrictInt
    lat: StrictFloat = Field(ge=-90, le=90, description="The point on the road.")
    lon: StrictFloat = Field(ge=-180, le=180)
    step: StrictFloat = Field(description="1 to 5 by halves (5 is Avoid).")
    reasons: list[str] = Field(max_length=6, description="Keys of the one-tap reasons.")
    other: str = Field(default="", max_length=1000, description="Other's words, at most 200.")
    ticket: str = Field(max_length=500)
    website: str = Field(default="", max_length=200, description="Left empty (a honeypot).")


SIGNED_OUT_THANKS = (
    "Thanks. Your suggestion was sent for review. Nothing changes on the map until it is reviewed."
)


@api.get(
    "/stress-suggestions/ticket",
    response={200: SuggestTicketOut, 400: ErrorOut, 403: StressEditErrorOut, 429: ErrorOut},
    summary="The short suggestion form's ticket for a road (anyone)",
)
@decorate_view(same_site_editor, ratelimit.rate_limited(ratelimit.SEGMENT_INFO), errors_as_json)
def stress_suggestion_ticket(request, params: Query[SuggestTicketIn], response: HttpResponse):
    from django.middleware.csrf import get_token

    from . import signed_out_suggestions as quick

    get_token(request)
    _private(response)
    return Status(
        200,
        {"ticket": quick.ticket(params.way), "reasons": [[k, w] for k, w in quick.REASONS.items()]},
    )


@api.post(
    "/stress-suggestions/signed-out",
    response={200: SuggestionCreatedOut, **SUGGESTION_RESPONSES},
    summary="Suggest a road's traffic stress level from the short form (anyone)",
)
@decorate_view(
    csrf_protected,
    json_body_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def stress_suggestion_signed_out(request, body: SignedOutSuggestionIn, response: HttpResponse):
    from . import signed_out_suggestions as quick
    from . import stress_edits

    _private(response)
    try:
        suggestion = quick.create(
            ratelimit.client_address(request),
            body.osm_way_id,
            body.lat,
            body.lon,
            body.step,
            body.reasons,
            body.other,
            body.ticket,
            body.website,
        )
    except quick.Dropped:
        return Status(200, {"id": 0, "message": SIGNED_OUT_THANKS})
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    return Status(200, {"id": suggestion.pk, "message": SIGNED_OUT_THANKS})


@api.get(
    "/stress-suggestions/open",
    response={200: SuggestionListOut, **SUGGESTION_RESPONSES},
    summary="The suggestions waiting for review (instance admin)",
)
@decorate_view(
    instance_admin_only(audited=False),
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def stress_suggestion_list(request, response: HttpResponse):
    from django.middleware.csrf import get_token

    from . import suggestions

    get_token(request)
    _private(response)
    return Status(
        200,
        {
            "suggestions": [
                suggestions.summary(s, request.user) for s in suggestions.open_suggestions()
            ]
        },
    )


class SuggestionReviewIn(Schema):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["agree", "disagree"]
    reason: str = Field(default="", max_length=1000, description="Optional, one line of 200.")


class SuggestionReviewOut(Schema):
    id: int
    message: str
    reviews: ReviewTalliesOut


@api.post(
    "/stress-suggestions/{suggestion_id}/review",
    response={200: SuggestionReviewOut, **SUGGESTION_RESPONSES},
    summary="Agree or disagree with a waiting suggestion: advice, not a decision (reviewer)",
)
@decorate_view(*REVIEW_WRITE)
def stress_suggestion_review(
    request, suggestion_id: int, body: SuggestionReviewIn, response: HttpResponse
):
    from . import stress_edits, suggestions

    try:
        suggestion = suggestions.review(
            request.user, suggestion_id, body.verdict == "agree", body.reason
        )
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    tallies = suggestions.tallies(suggestion, request.user)
    return Status(
        200,
        {
            "id": suggestion.pk,
            "message": f"You {body.verdict} with the suggestion for "
            f"{suggestion.road_name or 'the road'}. {suggestions.tallies_words(tallies)}. "
            "Approving still takes Approve now.",
            "reviews": tallies,
        },
    )


class MySuggestionIn(Schema):
    way: int = Field(ge=1, le=2**63 - 1, description="The road piece's OSM way id.")


class MySuggestionOut(Schema):
    id: int
    osm_way_id: int
    step: float
    words: str
    status: Literal["pending", "sent_to_discord", "approved", "deleted"]
    status_words: str
    created_at: str
    decided_at: str | None = None


class MySuggestionAnswerOut(Schema):
    suggestion: MySuggestionOut | None = Field(
        description="Your latest suggestion for the road, or null when you have sent none."
    )


@api.get(
    "/stress-suggestions/mine",
    response={
        200: MySuggestionAnswerOut,
        401: StressEditErrorOut,
        403: StressEditErrorOut,
        429: ErrorOut,
        500: ErrorOut,
    },
    summary="Your own latest suggestion for a road and its status (signed in)",
)
@decorate_view(
    same_site_editor,
    # Asked on every road panel a signed-in rider opens: a budget of its own, like the photo's.
    ratelimit.rate_limited(ratelimit.MY_SUGGESTION),
    errors_as_json,
)
def stress_suggestion_mine(request, params: Query[MySuggestionIn], response: HttpResponse):
    from . import suggestions

    if not signed_in(request):
        return _stress_error(401, "Sign in to see your suggestions.", code="signed_out")
    _private(response)
    return Status(200, {"suggestion": suggestions.mine(request.user, params.way)})


@api.post(
    "/stress-suggestions/{suggestion_id}/approve",
    response={200: SuggestionDoneOut, **SUGGESTION_RESPONSES},
    summary="Approve a suggestion now: applied at once as your edit (instance admin)",
)
@decorate_view(*REVIEW_WRITE)
def stress_suggestion_approve(request, suggestion_id: int, body: UndoIn, response: HttpResponse):
    from . import segment_info, stress_edits, suggestions

    try:
        suggestion, result = suggestions.approve(request.user, suggestion_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    words = segment_info.words_for(suggestion.tier, suggestion.half)
    level = "Avoid" if suggestion.tier == 5 else f"LTS {segment_info.step_label(suggestion.step)}"
    return Status(
        200,
        {
            "id": suggestion.pk,
            "status": suggestion.status,
            "message": f"Approved. {suggestion.road_name or 'The road'} is now {level}"
            + (f", {words[0].lower()}{words[1:]}." if suggestion.tier != 5 else ".")
            + " The map shows it now.",
            "generation": result.generation,
        },
    )


@api.post(
    "/stress-suggestions/{suggestion_id}/delete",
    response={200: SuggestionDoneOut, **SUGGESTION_RESPONSES},
    summary="Delete a suggestion (instance admin)",
)
@decorate_view(*REVIEW_WRITE)
def stress_suggestion_delete(request, suggestion_id: int, body: UndoIn, response: HttpResponse):
    from . import stress_edits, suggestions

    try:
        suggestion = suggestions.delete(request.user, suggestion_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(200, {"id": suggestion.pk, "status": suggestion.status, "message": "Deleted."})


@api.post(
    "/stress-suggestions/{suggestion_id}/discord",
    response={200: DiscordPostOut, **SUGGESTION_RESPONSES},
    summary="Send a suggestion to Discord: the poll to paste, and the suggestion marked sent",
)
@decorate_view(*REVIEW_WRITE)
def stress_suggestion_discord(request, suggestion_id: int, body: UndoIn, response: HttpResponse):
    from . import stress_edits, suggestions

    try:
        suggestion, post = suggestions.send_to_discord(
            request.user, suggestion_id, request.build_absolute_uri("/")
        )
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(
        200,
        {
            "id": suggestion.pk,
            "status": suggestion.status,
            "post": post.text,
            "characters": len(post.text),
            "options": [
                {"letter": o.letter, "label": o.label, "tier": o.tier} for o in post.options
            ],
        },
    )


# ---- Mass Ride hazards (FOLLOWUP-MASSRIDE-MAP part 3, OWNER-DECISIONS 325-327; core.mass_hazards)
#
# A rider the suggestion setting allows marks a road piece Caution or Warning, with a reason; an
# instance admin reviews it with the suggestions' three actions. The approved ones are a small
# public GeoJSON layer the Mass Ride map draws as side rails. The writes have every guard the
# suggestions have, and the same hourly count (ratelimit.SUGGEST_WRITES).

# How long a browser may keep the approved layer before asking again (a 304 when unchanged).
MASS_HAZARDS_MAX_AGE_S = 60


class MassHazardIn(Schema):
    model_config = ConfigDict(extra="forbid")

    osm_way_id: StrictInt
    lat: StrictFloat = Field(
        ge=-90, le=90, description="A spot on the road: checked, then dropped (never kept)."
    )
    lon: StrictFloat = Field(ge=-180, le=180)
    level: str = Field(max_length=16, description='"caution" or "warning".')
    reason: str = Field(max_length=2000, description="Required, at most 500 characters.")


class MassHazardOut(Schema):
    id: int
    osm_way_id: int
    road: str
    lat: float | None = Field(description="The road piece's middle (4 decimals), for the map.")
    lon: float | None
    level: Literal["caution", "warning"]
    level_name: str
    words: str
    reason: str
    status: Literal["pending", "sent_to_discord"]
    created_at: str
    sent_at: str | None = None


class MassHazardListOut(Schema):
    hazards: list[MassHazardOut]


class HazardPollOptionOut(Schema):
    letter: str
    label: str
    level: str | None = Field(description='"caution", "warning", "none" (no mark); null: not sure.')


class HazardDiscordPostOut(Schema):
    id: int
    status: str
    post: str = Field(description="Ready to paste: at most 2,000 characters, no mentions.")
    characters: int
    options: list[HazardPollOptionOut]


@api.get(
    "/mass-hazards",
    response={200: dict, 304: None, 403: ErrorOut, 429: ErrorOut, 500: ErrorOut},
    summary="The approved Mass Ride hazards, as GeoJSON (the Mass Ride map's side rails)",
)
@decorate_view(ratelimit.rate_limited(ratelimit.MASS_HAZARDS), same_site_only, errors_as_json)
def mass_hazard_layer(request, response: HttpResponse):
    """Public and cacheable: the level, its words, the reason and the road's name of each
    approved hazard, and the road piece's line. Nothing about who reported it."""
    from . import mass_hazards

    body, etag = mass_hazards.approved_layer()
    from .stress_tiles import _matches

    if _matches(request, etag):
        answer = HttpResponse(status=304)
    else:
        answer = JsonResponse(body, content_type="application/geo+json")
    answer["ETag"] = etag
    answer["Cache-Control"] = f"public, max-age={MASS_HAZARDS_MAX_AGE_S}"
    return answer


@api.post(
    "/mass-hazards",
    response={200: SuggestionCreatedOut, **SUGGESTION_RESPONSES},
    summary="Mark a road piece Caution or Warning for Mass Rides (a rider the settings allow)",
)
@decorate_view(*SUGGEST_WRITE)
def mass_hazard_create(request, body: MassHazardIn, response: HttpResponse):
    from . import mass_hazards, stress_edits

    try:
        hazard = mass_hazards.create(
            request.user, body.osm_way_id, body.lat, body.lon, body.level, body.reason
        )
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    _private(response)
    return Status(
        200,
        {
            "id": hazard.pk,
            "message": "Thanks. Your hazard report was sent to the map's admins. Nothing "
            "changes on the Mass Ride map until one of them reviews it.",
        },
    )


@api.get(
    "/mass-hazards/open",
    response={200: MassHazardListOut, **SUGGESTION_RESPONSES},
    summary="The hazard reports waiting for review (instance admin)",
)
@decorate_view(
    instance_admin_only(audited=False),
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def mass_hazard_list(request, response: HttpResponse):
    from django.middleware.csrf import get_token

    from . import mass_hazards

    get_token(request)
    _private(response)
    return Status(200, {"hazards": [mass_hazards.summary(h) for h in mass_hazards.open_reports()]})


@api.post(
    "/mass-hazards/{hazard_id}/approve",
    response={200: SuggestionDoneOut, **SUGGESTION_RESPONSES},
    summary="Approve a hazard report now: on the Mass Ride map at once (instance admin)",
)
@decorate_view(*REVIEW_WRITE)
def mass_hazard_approve(request, hazard_id: int, body: UndoIn, response: HttpResponse):
    from . import mass_hazards, stress_edits

    try:
        hazard = mass_hazards.approve(request.user, hazard_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    road = hazard.road_name or "The road"
    return Status(
        200,
        {
            "id": hazard.pk,
            "status": hazard.status,
            "message": f"Approved. {road} is marked {hazard.get_level_display()} on the Mass "
            "Ride map now.",
        },
    )


@api.post(
    "/mass-hazards/{hazard_id}/delete",
    response={200: SuggestionDoneOut, **SUGGESTION_RESPONSES},
    summary="Delete a hazard report (instance admin)",
)
@decorate_view(*REVIEW_WRITE)
def mass_hazard_delete(request, hazard_id: int, body: UndoIn, response: HttpResponse):
    from . import mass_hazards, stress_edits

    try:
        hazard = mass_hazards.delete(request.user, hazard_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(200, {"id": hazard.pk, "status": hazard.status, "message": "Deleted."})


@api.post(
    "/mass-hazards/{hazard_id}/discord",
    response={200: HazardDiscordPostOut, **SUGGESTION_RESPONSES},
    summary="Send a hazard report to Discord: the poll to paste, and the report marked sent",
)
@decorate_view(*REVIEW_WRITE)
def mass_hazard_discord(request, hazard_id: int, body: UndoIn, response: HttpResponse):
    from . import mass_hazards, stress_edits

    try:
        hazard, post = mass_hazards.send_to_discord(
            request.user, hazard_id, request.build_absolute_uri("/")
        )
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(
        200,
        {
            "id": hazard.pk,
            "status": hazard.status,
            "post": post.text,
            "characters": len(post.text),
            "options": [
                {"letter": o.letter, "label": o.label, "level": o.level} for o in post.options
            ],
        },
    )


# ---- Rider suggestions for junctions (OWNER-DECISIONS 232; core.junction_suggestions) ----


class JunctionAtOut(Schema):
    lon: float = Field(description="The junction's node, never the spot asked about.")
    lat: float
    name: str = Field(description='"Oak Street and Elm Street", or "An unnamed junction".')
    roads: list[str]


class JunctionSuggestionIn(Schema):
    model_config = ConfigDict(extra="forbid")

    lat: StrictFloat = Field(ge=-90, le=90, description="A spot at the junction; not stored.")
    lon: StrictFloat = Field(ge=-180, le=180)
    level: StrictInt | None = Field(
        default=None, description="2 easy, 3 takes patience, 4 hard, 5 Avoid; or null."
    )
    direction: Literal["more", "less"] | None = Field(
        default=None, description="More or less dangerous than shown; or null."
    )
    shown: Literal["none", "orange", "red", "avoid"] | None = Field(
        default=None, description="The marker the rider's route showed there, if any."
    )
    reason: str = Field(max_length=2000, description="Required, at most 500 characters.")


class JunctionSuggestionOut(Schema):
    id: int
    junction: str
    lat: float
    lon: float
    current_level: int
    current_words: str
    level: int
    words: str
    direction: Literal["more", "less"] | None = None
    reason: str
    status: Literal["pending", "sent_to_discord"]
    created_at: str
    sent_at: str | None = None
    # Approved Avoid junctions Approve now would withdraw there; the review warns first.
    withdraws_avoid: int = 0


class JunctionSuggestionListOut(Schema):
    suggestions: list[JunctionSuggestionOut]


@api.get(
    "/junction-suggestions/at",
    response={200: JunctionAtOut, **SUGGESTION_RESPONSES},
    summary="The junction nearest a spot, for a rider the settings allow to suggest",
)
@decorate_view(
    suggester_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def junction_at(request, lat: float, lon: float, response: HttpResponse):
    from django.middleware.csrf import get_token

    from . import junction_suggestions, stress_edits

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return _stress_error(400, "That spot is not on the map.", "lat")
    try:
        node = junction_suggestions.locate(lat, lon)
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    get_token(request)
    _private(response)
    return Status(
        200, {"lon": node.lon, "lat": node.lat, "name": node.name, "roads": list(node.roads)}
    )


@api.post(
    "/junction-suggestions",
    response={200: SuggestionCreatedOut, **SUGGESTION_RESPONSES},
    summary="Suggest a junction's danger level (a rider the settings allow)",
)
@decorate_view(*SUGGEST_WRITE)
def junction_suggestion_create(request, body: JunctionSuggestionIn, response: HttpResponse):
    from . import junction_suggestions, stress_edits

    try:
        suggestion = junction_suggestions.create(
            request.user,
            body.lat,
            body.lon,
            body.level,
            body.direction or "",
            body.shown,
            body.reason,
        )
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    _private(response)
    return Status(
        200,
        {
            "id": suggestion.pk,
            "message": f"Thanks. Your suggestion for {suggestion.name} was sent to the map's "
            "admins. Nothing changes on the map until one of them reviews it.",
        },
    )


@api.get(
    "/junction-suggestions/open",
    response={200: JunctionSuggestionListOut, **SUGGESTION_RESPONSES},
    summary="The junction suggestions waiting for review (instance admin)",
)
@decorate_view(
    instance_admin_only(audited=False),
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
def junction_suggestion_list(request, response: HttpResponse):
    from django.middleware.csrf import get_token

    from . import junction_suggestions

    get_token(request)
    _private(response)
    return Status(
        200,
        {
            "suggestions": [
                junction_suggestions.summary(s) for s in junction_suggestions.open_suggestions()
            ]
        },
    )


@api.post(
    "/junction-suggestions/{suggestion_id}/approve",
    response={200: SuggestionDoneOut, **SUGGESTION_RESPONSES},
    summary="Approve a junction suggestion now: the next plan uses it (instance admin)",
)
@decorate_view(*REVIEW_WRITE)
def junction_suggestion_approve(request, suggestion_id: int, body: UndoIn, response: HttpResponse):
    from . import junction_suggestions, stress_edits

    try:
        suggestion = junction_suggestions.approve(request.user, suggestion_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    if suggestion.target_level == junction_suggestions.AVOID:
        rated = "now rated Avoid"
    else:
        words = junction_suggestions.LEVEL_WORDS[suggestion.target_level]
        rated = f"now rated {words[0].lower()}{words[1:]}"
    return Status(
        200,
        {
            "id": suggestion.pk,
            "status": suggestion.status,
            "message": f"Approved. {suggestion.name} is {rated}. "
            "Routes planned from now on use it.",
        },
    )


@api.post(
    "/junction-suggestions/{suggestion_id}/delete",
    response={200: SuggestionDoneOut, **SUGGESTION_RESPONSES},
    summary="Delete a junction suggestion (instance admin)",
)
@decorate_view(*REVIEW_WRITE)
def junction_suggestion_delete(request, suggestion_id: int, body: UndoIn, response: HttpResponse):
    from . import junction_suggestions, stress_edits

    try:
        suggestion = junction_suggestions.delete(request.user, suggestion_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(200, {"id": suggestion.pk, "status": suggestion.status, "message": "Deleted."})


@api.post(
    "/junction-suggestions/{suggestion_id}/discord",
    response={200: DiscordPostOut, **SUGGESTION_RESPONSES},
    summary="Send a junction suggestion to Discord: the poll to paste, and it is marked sent",
)
@decorate_view(*REVIEW_WRITE)
def junction_suggestion_discord(request, suggestion_id: int, body: UndoIn, response: HttpResponse):
    from . import junction_suggestions, stress_edits

    try:
        suggestion, post = junction_suggestions.send_to_discord(
            request.user, suggestion_id, request.build_absolute_uri("/")
        )
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(
        200,
        {
            "id": suggestion.pk,
            "status": suggestion.status,
            "post": post.text,
            "characters": len(post.text),
            "options": [
                {"letter": o.letter, "label": o.label, "tier": o.tier} for o in post.options
            ],
        },
    )


# ---- Closures a reviewer entered or confirmed (v0.7.0 closures; core.reviewed_closures) ----
#
# A reviewer (an instance admin, or a reviewer role in a configured Discord server) enters a
# closure from the road panel, or confirms or rejects a rider's report, and ends one early. The
# closures take part in routing and the closure check as a feed's do, credited "Confirmed by a
# RouteMaker reviewer". Every write carries the CSRF token and is counted per account.


def reviewer_only(*, audited: bool):
    """A session of an account that may review closures, or 401 / 403."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            from . import reviewed_closures

            if not signed_in(request):
                return _stress_error(401, "Sign in to review closures.", code="signed_out")
            if not reviewed_closures.may_review(request.user):
                if audited:
                    _refused(request, request.user, "not a reviewer")
                doing = "enter a closure" if audited else "review closures"
                return _stress_error(
                    403, f"Only a RouteMaker reviewer can {doing}.", code="not_reviewer"
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


CLOSURE_REVIEW_WRITE = (
    ratelimit.user_rate_limited(ratelimit.SUGGEST_REVIEW_WRITES),
    csrf_protected,
    reviewer_only(audited=True),
    json_body_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)
CLOSURE_REVIEW_READ = (
    reviewer_only(audited=False),
    same_site_editor,
    ratelimit.rate_limited(ratelimit.STRESS_EDIT_CLIENT),
    errors_as_json,
)


class ReviewedClosureIn(Schema):
    model_config = ConfigDict(extra="forbid")

    osm_way_ids: list[StrictInt] | None = Field(
        default=None, description="The road pieces closed (at most 40), or a drawn `line`."
    )
    line: list[list[float]] | None = Field(
        default=None, description="A drawn stretch, [[lon, lat], ...], in place of the ways."
    )
    reason: str = Field(max_length=500, description="Required, at most 500 characters.")
    start: str | None = Field(default=None, description="The first day, YYYY-MM-DD (today).")
    end: str | None = Field(
        default=None, description="The last day, YYYY-MM-DD; none: until a reviewer ends it."
    )
    url: str = Field(default="", max_length=500, description="The source's link, optional.")


class ClosureConfirmIn(Schema):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        default="", max_length=500, description="The report's fixed reasons where empty."
    )
    start: str | None = None
    end: str | None = None
    url: str = Field(default="", max_length=500)


class ReviewedClosureOut(Schema):
    id: int
    road: str
    osm_way_ids: list[int]
    reason: str
    start: str | None
    end: str | None
    url: str | None
    when_text: str
    from_report: bool
    point: list[float] | None


class ClosureReportOut(Schema):
    id: int
    osm_way_id: int
    road: str
    reason: str
    reason_fixed: str = Field(description="The one-tap reasons' words only: the form's start.")
    lat: float
    lon: float
    created_at: str


class ClosureReviewOut(Schema):
    closures: list[ReviewedClosureOut]
    reports: list[ClosureReportOut]


class ClosureDoneOut(Schema):
    id: int
    message: str


class ClosureStretchOut(Schema):
    name: str
    osm_way_ids: list[int]
    pieces: int
    length_m: float
    capped: bool
    expected: str


class ClosureStretchAnswer(Schema):
    stretch: ClosureStretchOut | None


def _closure_said(closure) -> str:
    from . import reviewed_closures

    said = reviewed_closures.summary(closure)
    return (
        f"Closure confirmed: {said['road']}, {said['when_text'][0].lower()}"
        f"{said['when_text'][1:]}. New plans route round it within a minute."
    )


@api.get(
    "/closures/reviewed",
    response={200: ClosureReviewOut, **SUGGESTION_RESPONSES},
    summary="The closures reviewers confirmed, in force or to come, and riders' reports (reviewer)",
)
@decorate_view(*CLOSURE_REVIEW_READ)
def reviewed_closures_list(request, response: HttpResponse):
    from django.middleware.csrf import get_token

    from . import reviewed_closures

    get_token(request)
    _private(response)
    return Status(
        200,
        {
            "closures": [
                reviewed_closures.summary(c)
                for c in reviewed_closures.live_rows().order_by("start", "pk")
            ],
            "reports": [
                reviewed_closures.report_summary(r) for r in reviewed_closures.open_reports()
            ],
        },
    )


@api.get(
    "/closures/stretch/{osm_way_id}",
    response={200: ClosureStretchAnswer, **SUGGESTION_RESPONSES},
    summary="The named stretch a road piece is in, for Mark closed's extent choice (reviewer)",
)
@decorate_view(*CLOSURE_REVIEW_READ)
def reviewed_closure_stretch(request, osm_way_id: int, response: HttpResponse):
    from . import stress_edits

    try:
        stretch = stress_edits.stretch_state(osm_way_id)
    except stress_edits.EditRefused as refused:
        return _stress_error(refused.status, refused.message, refused.field, refused.code)
    _private(response)
    return Status(200, {"stretch": stretch})


@api.post(
    "/closures/reviewed",
    response={201: ClosureDoneOut, **SUGGESTION_RESPONSES},
    summary="Enter a closure: road pieces or a drawn line, reason, dates, source (reviewer)",
)
@decorate_view(*CLOSURE_REVIEW_WRITE)
def reviewed_closure_create(request, body: ReviewedClosureIn, response: HttpResponse):
    from . import reviewed_closures, stress_edits

    try:
        closure = reviewed_closures.create(
            request.user,
            way_ids=body.osm_way_ids,
            reason=body.reason,
            start=body.start,
            end=body.end,
            url=body.url,
            line=body.line,
        )
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(201, {"id": closure.pk, "message": _closure_said(closure)})


@api.post(
    "/closures/reviewed/{closure_id}/end",
    response={200: ClosureDoneOut, **SUGGESTION_RESPONSES},
    summary="End a confirmed closure now (reviewer)",
)
@decorate_view(*CLOSURE_REVIEW_WRITE)
def reviewed_closure_end(request, closure_id: int, body: UndoIn, response: HttpResponse):
    from . import reviewed_closures, stress_edits

    try:
        closure = reviewed_closures.end_now(request.user, closure_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    road = closure.road or "The drawn stretch"
    return Status(200, {"id": closure.pk, "message": f"Ended. {road} is open again for new plans."})


@api.post(
    "/closures/reports/{report_id}/confirm",
    response={201: ClosureDoneOut, **SUGGESTION_RESPONSES},
    summary="Confirm a rider's closure report: the closure on its road piece (reviewer)",
)
@decorate_view(*CLOSURE_REVIEW_WRITE)
def closure_report_confirm(request, report_id: int, body: ClosureConfirmIn, response: HttpResponse):
    from . import reviewed_closures, stress_edits

    try:
        closure = reviewed_closures.confirm_report(
            request.user, report_id, body.reason, body.start, body.end, body.url
        )
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(201, {"id": closure.pk, "message": _closure_said(closure)})


@api.post(
    "/closures/reports/{report_id}/reject",
    response={200: ClosureDoneOut, **SUGGESTION_RESPONSES},
    summary="Reject a rider's closure report (reviewer)",
)
@decorate_view(*CLOSURE_REVIEW_WRITE)
def closure_report_reject(request, report_id: int, body: UndoIn, response: HttpResponse):
    from . import reviewed_closures, stress_edits

    try:
        report = reviewed_closures.reject_report(request.user, report_id)
    except stress_edits.EditRefused as refused:
        return _edit_refusal(request, refused)
    _private(response)
    return Status(200, {"id": report.pk, "message": "Rejected. The report is deleted."})


# ---- Review: the instance admin's queue of roads to rule on (core.stress_review) ----
#
# GET /api/review/queues, /api/review/items, /api/review/map, /api/review/road/{way} and
# /api/review/rulings; POST /api/review/rulings and /api/review/rulings/{id}/undo. Instance admins
# only (401 signed out, 403 otherwise), with the editor's guards on the writes. What is listed here
# may carry ratings whose public use is pending (agency_lts.PENDING_AGENCIES): it is never cached
# and never reaches a rider.

REVIEW_QUEUES = Literal[
    "rebuild",
    "disagreement",
    "sidepath",
    "narrow_rural",
    "works_closure",
    "rematch",
    "painted_lane",
    "dc_no_bike",
]


class ReviewAnyOut(Schema):
    """The answer as `core.stress_review` builds it (queues, items, features or rulings)."""

    model_config = ConfigDict(extra="allow")


class ReviewItemsIn(Schema):
    queue: REVIEW_QUEUES = "rebuild"
    kind: str = Field(default="", max_length=40)
    source: str = Field(default="", max_length=40)
    area: str = Field(default="", max_length=200)
    open_only: bool = Field(default=True, description="Only roads with no ruling yet.")
    page: int = Field(default=1, ge=1, le=100000)
    per_page: int = Field(default=25, ge=1, le=100)
    way: int | None = Field(default=None, description="One road (a tap on Review's map).")


class ReviewMapIn(Schema):
    queues: str = Field(
        default="rebuild,disagreement",
        max_length=200,
        description="The lists to draw, comma-separated (Review's map switches).",
    )
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    zoom: float = Field(ge=0, le=24, description="Below 10 count badges; below 13 simplified.")


class ReviewNextIn(Schema):
    lists: str = Field(default="", max_length=200, description="The lists to go through, in order.")
    queue: REVIEW_QUEUES = "rebuild"
    way: int | None = Field(default=None, description="The road open now, if any.")
    direction: int = Field(default=1, ge=-1, le=1, description="1: after it; -1: before it.")
    open_only: bool = Field(default=True, description="Only roads with no ruling yet.")
    wrap: bool = Field(default=True, description="Past the last list, round to the first.")


def _review_lists(text: str) -> list[str]:
    from typing import get_args

    known = set(get_args(REVIEW_QUEUES))
    return [q for q in (part.strip() for part in text.split(",")) if q in known]


class ReviewRoadIn(Schema):
    queue: REVIEW_QUEUES | None = Field(
        default=None, description="rebuild: the facts of the build waiting in staging as well."
    )


class ReviewRulingIn(Schema):
    model_config = ConfigDict(extra="forbid")

    queue: REVIEW_QUEUES
    osm_way_ids: list[StrictInt] = Field(min_length=1, max_length=200)
    decision: Literal["accept", "reject", "set"]
    step: StrictFloat | None = Field(
        default=None, description="Change LTS: 1 to 5 by halves (5 is Avoid)."
    )
    reason: str = Field(default="", max_length=2000, description="Private; optional.")
    source: str | None = Field(
        default=None,
        max_length=40,
        description="Change LTS to the level this listed source holds; the evidence names it.",
    )


class ReviewRulingsIn(Schema):
    queue: REVIEW_QUEUES | None = None


REVIEW_RESPONSES = {200: ReviewAnyOut, **SUGGESTION_RESPONSES}

# Review's own counts (ratelimit.REVIEW_READS, REVIEW_RULINGS, REVIEW_RULINGS_CLIENT), never the
# road panel's editor's: browsing a list by keyboard reads fast, and a long review never spends
# the admin's editing budget.
REVIEW_READ = (
    ratelimit.rate_limited(ratelimit.REVIEW_READS),
    instance_admin_only(audited=False, doing="use Review"),
    same_site_editor,
    errors_as_json,
)
REVIEW_RULING_WRITE = (
    ratelimit.user_rate_limited(ratelimit.REVIEW_RULINGS),
    csrf_protected,
    instance_admin_only(audited=True, doing="use Review"),
    json_body_only,
    same_site_editor,
    ratelimit.rate_limited(ratelimit.REVIEW_RULINGS_CLIENT),
    errors_as_json,
)


def _review_answer(body: dict) -> JsonResponse:
    return _private(JsonResponse(body))


@api.get("/review/queues", response=REVIEW_RESPONSES, summary="Review's queues (instance admin)")
@decorate_view(*REVIEW_READ)
def review_queues(request):
    from django.middleware.csrf import get_token

    from . import stress_review

    get_token(request)
    return _review_answer({"queues": stress_review.queue_summary()})


@api.get("/review/items", response=REVIEW_RESPONSES, summary="A page of a queue (instance admin)")
@decorate_view(*REVIEW_READ)
def review_items(request, params: Query[ReviewItemsIn]):
    from . import stress_review

    return _review_answer(
        stress_review.page(
            params.queue,
            kind=params.kind,
            source=params.source,
            area=params.area,
            open_only=params.open_only,
            number=params.page,
            size=params.per_page,
            way=params.way,
        )
    )


@api.get(
    "/review/map",
    response=REVIEW_RESPONSES,
    summary="The listed roads in a view, for Review's map (instance admin)",
)
@decorate_view(*REVIEW_READ)
def review_map(request, params: Query[ReviewMapIn]):
    from . import stress_review

    # A view's roads only, at most stress_review.MAP_CAP; badges far out, simplified lines below
    # a street's zoom, both read from what was made when the lists were computed.
    box = (params.west, params.south, params.east, params.north)
    refusal = stress_review.view_refusal(*box, params.zoom)
    if refusal:
        return _private(JsonResponse({"error": refusal}, status=400))
    return _review_answer(stress_review.map_view(_review_lists(params.queues), box, params.zoom))


@api.get(
    "/review/next",
    response=REVIEW_RESPONSES,
    summary="The next road in the lists' order: Next discrepancy, Previous and Next road",
)
@decorate_view(*REVIEW_READ)
def review_next(request, params: Query[ReviewNextIn]):
    from . import stress_review

    found = stress_review.next_road(
        _review_lists(params.lists),
        params.queue,
        params.way,
        direction=1 if params.direction >= 0 else -1,
        open_only=params.open_only,
        wrap=params.wrap,
    )
    return _review_answer({"next": found})


@api.get(
    "/review/road/{osm_way_id}",
    response=REVIEW_RESPONSES,
    summary="The facts behind a road's rating and its history (instance admin)",
)
@decorate_view(*REVIEW_READ)
def review_road(request, osm_way_id: int, params: Query[ReviewRoadIn]):
    from . import stress_review

    return _review_answer(stress_review.road_detail(osm_way_id, params.queue or ""))


@api.get(
    "/review/street-photo",
    response={200: StreetPhotoOut, 204: None, **SUGGESTION_RESPONSES},
    summary="The road panel's street photo, for Review's rows and cards (instance admin)",
)
@decorate_view(*REVIEW_READ)
def review_street_photo(request, params: Query[StreetPhotoIn]):
    """The road panel's own lookup (core.street_photo), counted in Review's reads: a list shows a
    photo a row. Its image is the panel's own path (GET /api/street-photo/image/{id})."""
    from . import street_photo

    found = street_photo.client.photo(params.lon, params.lat, params.way)
    if found is None:
        return _private(HttpResponse(status=204))
    return _review_answer(found)


@api.get("/review/rulings", response=REVIEW_RESPONSES, summary="Recent rulings (instance admin)")
@decorate_view(*REVIEW_READ)
def review_rulings(request, params: Query[ReviewRulingsIn]):
    from . import stress_review

    return _review_answer({"rulings": stress_review.recent_rulings(params.queue)})


@api.post("/review/rulings", response=REVIEW_RESPONSES, summary="Rule on roads (instance admin)")
@decorate_view(*REVIEW_RULING_WRITE)
def review_rule(request, body: ReviewRulingIn):
    from . import stress_edits, stress_review

    try:
        made, refused = stress_review.rule(
            request.user,
            body.queue,
            body.osm_way_ids,
            body.decision,
            step=body.step,
            reason=body.reason,
            source=body.source,
        )
    except stress_edits.EditRefused as refusal:
        return _edit_refusal(request, refusal)
    generation = max((r.edit.generation for r in made if r.edit_id), default=None)
    # A road a stretch (every way of it is ruled, each its own row) or a way alone.
    count = len({r.stretch or r.osm_way_id for r in made})
    message = f"{count} road{'s' if count != 1 else ''} ruled" + (
        f"; {len(refused)} could not be: {refused[0]['error']}" if refused else "."
    )
    return _review_answer(
        {
            "rulings": [stress_review.ruling_out(r) for r in made],
            "refused": refused,
            "generation": generation,
            "message": message,
        }
    )


@api.post(
    "/review/rulings/{ruling_id}/undo",
    response=REVIEW_RESPONSES,
    summary="Undo a ruling within 30 minutes (instance admin)",
)
@decorate_view(*REVIEW_RULING_WRITE)
def review_undo(request, ruling_id: int, body: UndoIn):
    from . import stress_edits, stress_review

    try:
        ruling, generation = stress_review.undo(request.user, ruling_id)
    except stress_edits.EditRefused as refusal:
        return _edit_refusal(request, refusal)
    return _review_answer(
        {"ruling": stress_review.ruling_out(ruling), "generation": generation, "message": "Undone."}
    )
