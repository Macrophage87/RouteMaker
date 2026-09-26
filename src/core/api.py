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

Every error is `{"error": "..."}` with the status the shared contract names:
400 for input this API will not route (including a request too long to be
worth routing), 422 when the router finds no route, 429 with Retry-After when
the client's budget is spent or it already has two routes in flight, 502 when
the router does not answer, 503 with Retry-After when the deployment's routing
slots are all busy or the request's time budget ran out, and 500 for anything
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
from pydantic import ConfigDict, field_validator

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

# The longest request this planner routes, as the sum of the straight-line
# distances between consecutive points. A route's cost grows with its length -
# the /route search, then one /trace_attributes per leg, then the stress join
# over every vertex - and the operations probe put a 25-point zig-zag across
# the box at 590 km and 15 s on its own, with five of them from one client
# holding all five of the stack's gunicorn workers for 22-43 s and /healthz
# unanswered for 21 s. 150 km of straight line is a long day's ride and more
# than any reference route (the longest rural loop is under 50 km), so nobody
# planning a ride meets it; a caller wanting more splits the route.
MAX_STRAIGHT_LINE_M = 150_000
TOO_LONG = "the route is too long to plan in one request; split it into shorter parts"

# The Retry-After on a 503 for a request whose time budget ran out.
DEADLINE_RETRY_S = 30

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


class RouteIn(Schema):
    model_config = ConfigDict(extra="forbid")

    points: list[LonLat] = Field(
        min_length=MIN_POINTS,
        max_length=MAX_POINTS,
        description="[lon, lat] pairs, start first, each inside the coverage area.",
    )
    preset: PresetName

    @field_validator("points")
    @classmethod
    def inside_coverage(cls, points: list[list[float]]) -> list[list[float]]:
        west, south, east, north = settings.COVERAGE_BBOX
        for index, (lon, lat) in enumerate(points):
            if not (west <= lon <= east and south <= lat <= north):
                raise ValueError(f"point {index} is outside the area this map covers")
        straight = sum(
            haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False)
        )
        if straight > MAX_STRAIGHT_LINE_M:
            raise ValueError(TOO_LONG)
        return points


class LineString(Schema):
    type: Literal["LineString"]
    coordinates: list[list[float]]


class StressOut(Schema):
    model_config = ConfigDict(populate_by_name=True)

    tier_1: float = Field(alias="1")
    tier_2: float = Field(alias="2")
    tier_3: float = Field(alias="3")
    tier_4: float = Field(alias="4")
    unknown: float


class RouteOut(Schema):
    preset: PresetName
    variant: Literal["standard", "no-trail", "ebike"]
    geometry: LineString
    distance_m: float
    duration_s: float
    climb_m: float
    descent_m: float
    stress_m: StressOut
    attribution: list[str]


def _error(status: int, message: str) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@api.exception_handler(ValidationError)
def invalid_input(request, exc: ValidationError):
    """Ninja's 422 for a body it cannot validate is the contract's 400."""
    problems = []
    for error in exc.errors[:5]:
        where = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        problems.append(f"{where}: {error.get('msg', 'invalid')}" if where else error.get("msg"))
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
        422: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        502: ErrorOut,
        503: ErrorOut,
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
    try:
        return Status(200, routing.plan(body.points, body.preset))
    except routing.TooLong:
        return Status(400, {"error": TOO_LONG})
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
        response["Retry-After"] = str(DEADLINE_RETRY_S)
        return Status(503, {"error": "Planning this route took too long; try again shortly."})
