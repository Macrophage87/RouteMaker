"""Send to Wahoo through the rider's connection (core.wahoo): the route shown, added to their Wahoo
app's routes with Wahoo's Cloud API (POST /v1/routes), from where the app sends it to their ELEMNT.

Wahoo takes the route as a FIT course file, so the app makes it, with its turn cues, fitted to the
Wahoo profile (frontend lib/course.ts), exactly as Download FIT does. The line comes with it for
what Wahoo asks beside the file: the start, the distance, the climb and the descent.

A saved route sent again updates its Wahoo route in place (WahooLink.routes); a route not saved is
a new one each time. Every route sent is remembered on the link, so deleting the account can take
them out of the rider's Wahoo app too (the owner, 2026-10-23). HTTP goes through
`wahoo.Transport`, replaced in the tests.
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid

from django.db import transaction
from django.utils import timezone

from . import wahoo
from .garmin_courses import BadLine, _metres, read_line

log = logging.getLogger(__name__)

# A FIT course of the longest route a Wahoo keeps is well under this (lib/deviceProfiles.ts).
MAX_FIT_BYTES = 2 * 1024 * 1024
MAX_NAME = 100
# Every Wahoo route family that is cycling is BIKING (0); the kind of ride is not Wahoo's to know.
BIKING = 0
# How many routes one link remembers; past it, routes not saved are sent but not remembered.
MAX_REMEMBERED = 500

BAD_FILE = "The course file is not a FIT file."
TOO_BIG = "This route's course file is too large to send to Wahoo."
NO_PERMISSION = "Wahoo has not allowed RouteMaker to add routes. Connect Wahoo again in Settings."
BUSY = "Wahoo is taking too many routes just now."
REFUSED = "Wahoo did not take the route."
NOT_TAKEN = "Wahoo could not read this route."


def read_fit(raw) -> bytes:
    """The FIT file, from base64. Raises BadLine."""
    if not isinstance(raw, str) or not raw:
        raise BadLine(BAD_FILE)
    if len(raw) > (MAX_FIT_BYTES * 4) // 3 + 4:
        raise BadLine(TOO_BIG)
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as error:
        raise BadLine(BAD_FILE) from error
    # A FIT file's header is 12 or 14 bytes, with ".FIT" at bytes 8 to 11.
    if len(data) < 14 or data[0] not in (12, 14) or data[8:12] != b".FIT":
        raise BadLine(BAD_FILE)
    return data


def build(name: str, raw_line, raw_fit) -> dict:
    """The form fields Wahoo's routes endpoints take, without `external_id` (POST only). Raises
    BadLine."""
    points = read_line(raw_line)
    fit = read_fit(raw_fit)
    distance = sum(_metres(a, b) for a, b in zip(points, points[1:], strict=False))
    known = [p[2] for p in points if p[2] is not None]
    rises = [b - a for a, b in zip(known, known[1:], strict=False)]
    name = (str(name).strip() or "RouteMaker route")[:MAX_NAME]
    return {
        "route[file]": "data:application/vnd.fit;base64," + base64.b64encode(fit).decode("ascii"),
        "route[filename]": "route.fit",
        "route[name]": name,
        "route[description]": "Planned in RouteMaker",
        "route[workout_type_family_id]": BIKING,
        "route[start_lat]": round(points[0][1], 7),
        "route[start_lng]": round(points[0][0], 7),
        "route[distance]": round(distance, 1),
        "route[ascent]": round(sum(r for r in rises if r > 0), 1),
        "route[descent]": round(-sum(r for r in rises if r < 0), 1),
    }


def _call(user, method: str, url: str, form: dict, transport: wahoo.Transport) -> tuple[int, dict]:
    """One routes call; Wahoo refusing the token is answered by one refresh and a retry."""
    from .wahoo_views import access_for

    status, answer = transport.send_form(method, url, form, access_for(user, transport))
    if status == 401:
        status, answer = transport.send_form(
            method, url, form, access_for(user, transport, fresh=True)
        )
    if status not in (200, 201, 204, 404):
        # What Wahoo said, for the operator: never the token, at most the start of its answer.
        log.warning("Wahoo routes %s answered %s: %.300s", method, status, answer)
    if status == 401:
        raise wahoo.WahooError(REFUSED)
    if status == 422:
        raise wahoo.WahooError(NOT_TAKEN)
    if status == 429:
        raise wahoo.WahooError(BUSY)
    return status, answer


def send(user, form: dict, saved_route_id: int | None, transport: wahoo.Transport | None = None):
    """Add the route to the rider's Wahoo app, or update the one this saved route was sent as.
    Returns ("added" | "updated", Wahoo route id). Raises NotConnected or WahooError."""
    from .models import SavedRoute, WahooLink

    transport = transport or wahoo.Transport()
    key = None
    if (
        saved_route_id is not None
        and SavedRoute.objects.filter(pk=saved_route_id, user=user).exists()
    ):
        key = str(saved_route_id)
    link = WahooLink.objects.filter(user=user).first()
    known = (link.routes or {}).get(key) if link and key else None
    stamp = {"route[provider_updated_at]": timezone.now().isoformat()}
    if known is not None:
        status, _ = _call(user, "PUT", f"{wahoo.ROUTES_URL}/{known}", {**form, **stamp}, transport)
        if status in (200, 201, 204):
            return "updated", known
        if status not in (403, 404):
            raise wahoo.WahooError(REFUSED)
        # Deleted in the Wahoo app since (404), or not this Wahoo account's (403): added again.
    external = {"route[external_id]": f"routemaker-{uuid.uuid4().hex}"}
    status, answer = _call(user, "POST", wahoo.ROUTES_URL, {**form, **stamp, **external}, transport)
    if status == 403:
        raise wahoo.WahooError(NO_PERMISSION)
    route_id = answer.get("id") if status in (200, 201) else None
    if not isinstance(route_id, int | str) or isinstance(route_id, bool) or route_id == "":
        raise wahoo.WahooError(REFUSED)
    _remember(user, key or f"sent-{route_id}", route_id)
    return "added", route_id


def _remember(user, key: str, route_id) -> None:
    from .models import WahooLink

    with transaction.atomic():
        link = WahooLink.objects.select_for_update().filter(user=user).first()
        if link is None:
            return
        routes = dict(link.routes or {})
        if key not in routes and len(routes) >= MAX_REMEMBERED and key.startswith("sent-"):
            return
        routes[key] = route_id
        link.routes = routes
        link.save(update_fields=["routes"])
