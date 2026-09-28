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
from ninja import Field, NinjaAPI, Schema, Status
from ninja.decorators import decorate_view
from ninja.errors import HttpError, ValidationError
from pydantic import ConfigDict, StrictBool, StrictInt, field_validator, model_validator

from routemaker import ridetime
from routemaker.geo import Point, haversine

from . import presets, ratelimit, routing

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


def too_long() -> str:
    """The refusal past MAX_SPAN_M, naming the figure so a rider knows the limit."""
    return (
        f"the route is longer than {MAX_SPAN_M // 1000} km in straight lines, which is too "
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
        description="Set true to plan a signed-out request longer than 150 km of straight line.",
    )
    stress: StrictInt | None = Field(
        default=None,
        ge=presets.STRESS_MIN,
        le=presets.STRESS_MAX,
        description=(
            "The traffic-stress slider: 0 is traffic tolerant (the planner warns at 10 or"
            " below; it is not the fastest route), 100 keeps to low-stress ways unless avoiding"
            " them takes much longer. Absent: the preset's own start."
        ),
    )
    hills: StrictInt | None = Field(
        default=None,
        ge=presets.HILLS_MIN,
        le=presets.HILLS_MAX,
        description=(
            "The hills slider: -100 avoids climbing, 0 is the fastest time, above 0 looks for"
            " climbs among the router's alternatives (two-point plans up to 50 km of straight"
            " line). Absent: the"
            " preset's own start. Mass Ride does not seek climbs."
        ),
    )
    when: WhenName | None = Field(
        default=None,
        description=(
            "When the ride is: weekend, weekday_rush (Mon-Fri 07-10 and 16-19) or weekday_offpeak."
            " Absent: the setting of the moment the plan is made, in the region's time."
        ),
    )
    carrying: CarryingName | None = Field(
        default=None,
        description="Cargo Bike only: what the bike carries, which sets the stress slider's start.",
    )
    assist: StrictBool = Field(
        default=False,
        description=(
            "Cargo Bike only: electric assist. Routes under e-bike rules at a somewhat faster"
            " pace; the hills slider keeps Cargo Bike's start."
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
        if self.stress is not None and self.stress > preset.stress_max:
            raise ValueError(
                "Mass Ride keeps to the most direct roadway: a field that takes the road is not"
                " steered onto side streets, so the traffic slider stays at its lowest"
            )
        if self.assist and preset.assist_speed_kmh is None:
            raise ValueError("assist applies to the Cargo Bike ride type only")
        return self

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


class DialsOut(Schema):
    """The slider positions and ride time the route was planned with."""

    stress: int
    hills: int
    when: WhenName
    carrying: CarryingName | None
    assist: bool


class HillsSeekOut(Schema):
    """Present when the hills slider was past its detent."""

    candidates: int = Field(description="Routes compared, the direct one included.")
    chosen: int = Field(description="Which was kept; 0 is the direct route.")
    extra_climb_m: float
    extra_distance_m: float
    limited: Literal["two_points", "long_ride", "timed_out"] | None = Field(
        description="Why no alternatives were compared, if none were."
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


class RouteOut(Schema):
    preset: PresetName
    variant: Literal["standard", "no-trail", "ebike", "weekend"]
    geometry: LineString
    distance_m: float
    duration_s: float
    climb_m: float
    descent_m: float
    stress_m: StressOut
    facility_m: FacilityOut
    stress_adjustments: list[StressAdjustmentOut]
    dials: DialsOut
    hills_seek: HillsSeekOut | None
    hills_avoid: HillsAvoidOut | None
    attribution: list[str]
    # Index in geometry.coordinates of each leg's last vertex, one per leg
    # (points - 1); a leg starts where the one before it ends.
    leg_ends: list[int]


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
    return _error(500, "Something went wrong planning this route.")


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
    span = span_m(body.points)
    if span <= CONFIRM_SPAN_M:
        return _plan(request, body, response, long_ride=False)
    if not body.confirm_long and not signed_in(request):
        return Status(
            409,
            {
                "error": (
                    f"This is a long ride, about {round(span / 1000)} km in straight lines. "
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


def _plan(request, body: RouteIn, response: HttpResponse, long_ride: bool):
    started = getattr(request, "routing_started", None)
    try:
        dials = routing.Dials(
            stress=body.stress,
            hills=body.hills,
            when=body.when,
            carrying=body.carrying,
            assist=body.assist,
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
                " Mass Ride routes only on roadways, and removing trails can leave"
                " no roadway-legal connection between two points."
            )
        return Status(422, {"error": message})
    except routing.RouterUnavailable:
        return Status(502, {"error": "The router is not answering; try again shortly."})
    except routing.DeadlineExceeded:
        # A JsonResponse rather than Status, so an ordinary 503 stays exactly
        # {"error"} instead of carrying "code": null.
        if long_ride:
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
