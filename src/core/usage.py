"""Anonymous daily usage totals: how many times each tool was used on each day, nothing more.

The owner, 2026-11-13: "Yes to anonymous data totals." Each day the server adds one to a counter
per tool used (a route planned, a search, a ride started, a connector tool called), so it shows
what people actually use as testers join. A row is a day, a tool's name and a number
(`DailyUsage`): no route, place, account, internet address or time of day is kept, so the privacy
rule (nothing identifying on the server for more than 2 minutes) holds by construction. The day is
Washington's (`DAY_ZONE`), not the server's UTC, so a 9 PM ride is counted on the day it was ridden.

Three ways in, all through `tally`:
- `UsageMiddleware` counts a successful answer from the API routes in `ROUTES` (the server sees
  these anyway).
- POST /api/usage (core.api) counts what only the browser sees: a ride, walk or run started
  (`CLIENT_TOOLS`). It takes a name from that list and nothing else.
- core.connector counts each tools/call that answered, as one "assistant connector" total
  (not per tool), leaving out plans marked `test: true` (agents checking the app).

Garmin and Wahoo sends share one total, as a per-service row on a quiet day could point to the
few linked accounts. A failed count is logged and dropped: counting never changes or slows an
answer by more than its one upsert. The totals are read in the admin (core.admin, instance
admins only).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db import DatabaseError, connection, transaction

logger = logging.getLogger(__name__)

DAY_ZONE = ZoneInfo("America/New_York")

# (method, Django route) -> the tool's name in the totals. Only things a rider does on purpose:
# not the map's tiles, the polls a ride repeats every few seconds, or the account's own reads.
# Nothing on a Group or Mass Ride link (api/rides/...): those endpoints write nothing to the
# database at all (tests/test_ride_presence.py), and a count would be the one write.
ROUTES: dict[tuple[str, str], str] = {
    ("POST", "api/route"): "plan route",
    ("POST", "api/route/loop-shapes"): "plan loop",
    ("POST", "api/route/neighbours"): "more direct or calmer",
    ("POST", "api/stop-order"): "order stops",
    ("POST", "api/match"): "import route",
    ("POST", "api/reach"): "reach",
    ("GET", "api/geocode"): "place search requests",  # the typeahead: one per pause in typing
    ("GET", "api/segment-info"): "road panel",
    ("GET", "api/scenic-roads"): "scenic roads",
    ("GET", "api/climbs-near"): "climbs near",
    ("POST", "api/bikeshare/stations"): "bikeshare",
    ("GET", "api/transit/station-times"): "transit times",
    ("POST", "api/offline/network"): "offline route",
    # Not GET api/offline/packs: Settings asks for the list each time it opens, so it would count
    # opened Settings, not packs kept (the v0.27.0 release review).
    ("POST", "api/me/routes"): "save route",
    ("POST", "api/shared-routes"): "share link",
    # One total for both: a per-service row on a quiet day would point to the few linked accounts.
    ("POST", "api/me/garmin/courses"): "send to Garmin or Wahoo",
    ("POST", "api/me/wahoo/routes"): "send to Garmin or Wahoo",
    ("POST", "api/report311/where"): "311 report",
    ("POST", "api/stress-suggestions"): "road suggestion",
    ("POST", "api/stress-suggestions/signed-out"): "road suggestion",
    ("POST", "api/junction-suggestions"): "junction suggestion",
    ("POST", "api/mass-hazards"): "mass ride hazard",
    ("POST", "api/feedback"): "feedback",
}

# What the browser reports itself (POST /api/usage): only these names are counted.
CLIENT_TOOLS = frozenset({"ride", "walk", "run"})

# One total for every assistant tool call, for the same reason: a per-tool row could point to
# the few riders who connected an assistant.
CONNECTOR = "assistant connector"

_TALLY = """
INSERT INTO daily_usage (day, tool, count) VALUES (%s, %s, 1)
ON CONFLICT (day, tool) DO UPDATE SET count = daily_usage.count + 1
"""


def today(now: datetime | None = None) -> date:
    """Washington's date now (or at `now`)."""
    return (now or datetime.now(DAY_ZONE)).astimezone(DAY_ZONE).date()


def tally(tool: str) -> None:
    """Add one to today's count for `tool`. Never raises."""
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(_TALLY, [today(), tool[:64]])
    except DatabaseError:
        logger.warning("usage count not kept for %s", tool)


class UsageMiddleware:
    """Counts a successful answer from one of `ROUTES`, after the view has answered."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, "resolver_match", None)
        if match is not None and response.status_code < 400:
            tool = ROUTES.get((request.method, match.route))
            if tool is not None:
                tally(tool)
        return response
