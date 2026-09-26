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
400 for input this API will not route, 422 when the router finds no route, 429
with Retry-After when the client's budget is spent, and 502 when the router
does not answer.
"""

from __future__ import annotations

from functools import wraps
from typing import Annotated, Literal

from django.conf import settings
from django.http import JsonResponse
from ninja import Field, NinjaAPI, Schema, Status
from ninja.decorators import decorate_view
from ninja.errors import HttpError, ValidationError
from pydantic import ConfigDict, field_validator

from . import presets, ratelimit, routing

# The largest body worth parsing. Twenty-five points with generous precision
# and whitespace is well under 2 KB; Django's own ceiling is 2.5 MB, which is a
# thousand times what this endpoint can use and all of it parsed before the
# point count is checked.
MAX_BODY_BYTES = 8 * 1024

MIN_POINTS = 2
MAX_POINTS = 25

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
    """Ninja's 422 for a body it cannot parse or validate is the contract's 400."""
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


def json_body_only(view):
    """Refuse an oversized or non-JSON body before anything parses it.

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
    response={200: RouteOut, 400: ErrorOut, 422: ErrorOut, 429: ErrorOut, 502: ErrorOut},
    summary="Plan a route through two to twenty-five points on a preset",
    by_alias=True,
)
# Ninja applies these innermost first, so the rate limit is the outermost: a
# refused client costs one upsert and never has its body read.
@decorate_view(json_body_only, ratelimit.rate_limited(ratelimit.ROUTING))
def route(request, body: RouteIn):
    try:
        return Status(200, routing.plan(body.points, body.preset))
    except routing.NoRoute:
        message = "No route joins these points on this preset."
        if presets.PRESETS[body.preset].variant == "no-trail":
            # PLAN, Routing model: a no-route result on the no-trail variant
            # reports the disconnection rather than failing blankly.
            message += (
                " Mass Ride routes only on roadways, and removing trails can leave"
                " no roadway-legal connection between two points."
            )
        return Status(422, {"error": message})
    except routing.RouterUnavailable:
        return Status(502, {"error": "The router is not answering; try again shortly."})
