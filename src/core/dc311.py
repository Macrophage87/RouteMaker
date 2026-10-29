"""Sending a Ride mode report to DC 311 from the server (v0.7.0 "Go riding fixes" item 3).

The owner, 2026-10-15: "When reporting to 311 you should be able to select the report and send
it. Too many steps in between." So in Ride mode a 311 report is: tap 311, tap the problem, sent.

DC 311 publishes an Open311 GeoReport v2 endpoint (wiki.open311.org/GeoReport_v2/Servers lists
Washington, D.C. at app.311.dc.gov/cwi/Open311/v2 with jurisdiction `dc.gov`). GeoReport v2's
"POST Service Request" requires an API key that the city issues (the spec's method table:
"Requires API Key: Yes"); DC lists no public way to get one and no test server, and the endpoint
could not be reached from where this was written (2026-10-15). So this sender exists but is off
unless the deployment sets DC311_API_KEY (the owner requests it from DC). Off, Ride mode keeps
the problem in the 311 log for the rider to send (DC's Text to 311 is gone). The privacy policy
names no server send while it is off: setting the key needs its DC 311 lines back first (the
owner, 2026-10-29).

What leaves the server, and only when the key is set and the rider tapped a problem: the
problem's service code, the point on the route the rider was at (rounded to 5 decimals, about
1 m), and the report's words (the problem, the street in the route's own names, the rider's
note). Nothing is kept or logged: not the position, not the words, not the answer's id.

The service codes are DC's own, read from its `services.json` and matched by name
(SERVICE_NAMES), at most once a day; a problem with no matching service (or "Something else")
is not sent from here, and stays in the rider's 311 log.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)

ENDPOINT = "https://app.311.dc.gov/cwi/Open311/v2"
JURISDICTION = "dc.gov"
TIMEOUT_S = 10.0
SERVICES_MAX_AGE_S = 24 * 3600
DESCRIPTION_MAX = 500

# Washington, DC's bounding box, a little generous: a report from outside it is refused.
DC_BOX = (-77.12, 38.79, -76.90, 39.00)

# Ride mode's problems (frontend lib/report311.ts REPORT_KINDS) and the words a DC service's
# name is matched by, first match wins. "other" has none: the rider's text goes by message.
SERVICE_NAMES: dict[str, tuple[str, ...]] = {
    "pothole": ("pothole",),
    "streetlight": ("streetlight", "street light"),
    "tree": ("tree removal", "tree inspection", "tree"),
    "bikeLane": ("parking enforcement",),
    "obstruction": ("obstruct", "blocked"),
    "other": (),
}
KINDS = tuple(SERVICE_NAMES)


# A send is a signed-in rider's, and needs a ticket from the page (GET /api/report311 gives one
# while the sender is on), signed by the server for that account and good for `TICKET_MAX_AGE_S`.
# Each account sends at most ratelimit.REPORT_311_ACCOUNT an hour; and however many riders send, at
# most `HOURLY_MAX` reports an hour leave this server for DC (`GLOBAL_SCOPE`, counted in the
# database so every worker shares it), on top of the per-address limit (ratelimit.REPORT_311).
# Signed out, the problem stays in the 311 log, as it does with the sender off.
TICKET_SALT = "routemaker/report-311/v1"
TICKET_MAX_AGE_S = 15 * 60
HOURLY_MAX = 60
GLOBAL_SCOPE = "report-311-all"


def ticket(who: str = "") -> str:
    """What the page sends back with a report: proof it asked this server first, signed, dated,
    and for whom (`who`, a keyed digest of the account, never its id)."""
    return signing.dumps({"r": 311, "u": who}, salt=TICKET_SALT, compress=True)


def ticket_ok(value, who: str = "") -> bool:
    if not isinstance(value, str) or not value or len(value) > 512:
        return False
    try:
        found = signing.loads(value, salt=TICKET_SALT, max_age=TICKET_MAX_AGE_S)
    except signing.BadSignature:
        return False
    return isinstance(found, dict) and found.get("r") == 311 and found.get("u", "") == who


class NotSent(Exception):
    """The report was not sent; `code` says why, for the client to fall back on."""

    def __init__(self, code: str, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def enabled() -> bool:
    """Whether the sender is on: the deployment set DC311_API_KEY."""
    return bool(getattr(settings, "DC311_API_KEY", ""))


def _get(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        return json.loads(response.read())


def _post(url: str, form: dict[str, str]) -> object:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        return json.loads(response.read())


_services: tuple[float, list[dict]] | None = None


def forget_services() -> None:
    """For tests: the next report reads DC's services afresh."""
    global _services
    _services = None


def services() -> list[dict]:
    """DC's service list (`services.json`), at most once a day."""
    global _services
    now = time.monotonic()
    if _services is not None and now - _services[0] < SERVICES_MAX_AGE_S:
        return _services[1]
    query = urllib.parse.urlencode({"jurisdiction_id": JURISDICTION})
    answer = _get(f"{ENDPOINT}/services.json?{query}")
    rows = [row for row in answer if isinstance(row, dict)] if isinstance(answer, list) else []
    _services = (now, rows)
    return rows


def service_code(kind: str, rows: list[dict]) -> str | None:
    """The code of DC's service for a problem, by the service's name; None where none fits."""
    for words in SERVICE_NAMES.get(kind, ()):
        for row in rows:
            name = str(row.get("service_name") or "").lower()
            code = row.get("service_code")
            if words in name and code not in (None, ""):
                return str(code)
    return None


def send(kind: str, lat: float, lon: float, description: str) -> str | None:
    """Send one report; the request's id (or token) as DC answers it, or None where it gave
    none. Raises NotSent where it was not sent."""
    if not enabled():
        raise NotSent("dc311_off", "Sending to DC 311 from here is off.")
    if kind not in SERVICE_NAMES:
        raise NotSent("bad_kind", "Unknown problem.", 400)
    west, south, east, north = DC_BOX
    if not (west <= lon <= east and south <= lat <= north):
        raise NotSent("outside_dc", "Reports to DC 311 are for Washington, DC only.", 400)
    try:
        code = service_code(kind, services())
    except (OSError, ValueError, urllib.error.URLError):
        logger.warning("DC 311's service list could not be read")
        raise NotSent("dc311_unreachable", "DC 311 could not be reached.", 502) from None
    if code is None:
        raise NotSent("no_service", "DC 311 has no matching request to send this as.")
    form = {
        "api_key": settings.DC311_API_KEY,
        "jurisdiction_id": JURISDICTION,
        "service_code": code,
        "lat": f"{lat:.5f}",
        "long": f"{lon:.5f}",
        "description": description[:DESCRIPTION_MAX],
    }
    try:
        answer = _post(f"{ENDPOINT}/requests.json", form)
    except urllib.error.HTTPError as error:
        # The status only: never the form, which carries the key and the rider's place.
        logger.warning("DC 311 refused a report: HTTP %s", error.code)
        raise NotSent("dc311_refused", "DC 311 did not take the report.", 502) from None
    except (OSError, ValueError, urllib.error.URLError):
        logger.warning("DC 311 could not be reached to send a report")
        raise NotSent("dc311_unreachable", "DC 311 could not be reached.", 502) from None
    first = answer[0] if isinstance(answer, list) and answer else {}
    if not isinstance(first, dict):
        return None
    ident = first.get("service_request_id") or first.get("token")
    return str(ident) if ident not in (None, "") else None
