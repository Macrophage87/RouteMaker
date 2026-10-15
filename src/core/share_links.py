"""Short map links resolved for "Open shared locations in RouteMaker" (v0.7.0).

The owner, 2026-10-14 16:23 UTC: "In some links that share a location it's possible to open in
Google maps, waze, etc. Can this app be added to the list?" The plan: a place shared to RouteMaker
(Android's share sheet) or pasted into its search box opens as the destination. Most map links
carry their coordinates and are read in the browser (frontend/src/lib/sharedLocation.ts); a short
link (maps.app.goo.gl, goo.gl/maps, maps.apple) carries only an id, and the browser cannot follow
its redirect to another site, so POST /api/share/resolve follows it here.

Only those short-link hosts are asked, over https; each redirect is followed by hand, at most
`MAX_HOPS`, and only to a map site's own hosts (`FOLLOW_HOSTS`); no page body is read. The answer
is the full link the short one stands for, which the browser then reads for its place. The
request carries nothing of the visitor (no address, no cookie; the same `User-Agent` for all),
and the link is in the POST body, so it is in no URL or log line, and it is kept nowhere.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

# Links that are only an id for a map link, and the paths they use.
SHORT_HOSTS = {
    "maps.app.goo.gl": "/",
    "goo.gl": "/maps/",
    "maps.apple": "/",
}
# Where a short link's redirects may go: the short hosts and the map sites they stand for.
FOLLOW_HOSTS = frozenset(
    {
        *SHORT_HOSTS,
        "www.google.com",
        "google.com",
        "maps.google.com",
        "consent.google.com",
        "maps.apple.com",
    }
)
MAX_HOPS = 5
TIMEOUT_S = 4.0
MAX_URL = 2048
USER_AGENT = "RouteMaker-share-links"

# One GET without following: the redirect's Location, or None when the answer is not a redirect.
LocationOf = Callable[[str, float], "str | None"]


class NotAShortLink(ValueError):
    """The link is not a short map link this resolves."""


class Unresolved(Exception):
    """The short link could not be followed to a map link."""


def is_short_link(url: str) -> bool:
    parts = urllib.parse.urlsplit(url.strip())
    prefix = SHORT_HOSTS.get(parts.hostname or "")
    return (
        parts.scheme == "https"
        and prefix is not None
        and not parts.username
        and parts.port in (None, 443)
        and parts.path.startswith(prefix)
        and len(parts.path) > len(prefix)
    )


def _allowed_hop(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname in FOLLOW_HOSTS
        and not parts.username
        and parts.port in (None, 443)
    )


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib then raises HTTPError, whose Location is read below


_OPENER = urllib.request.build_opener(_NoFollow)


def location_of(url: str, timeout: float) -> str | None:
    """GET one link without following it: the redirect's Location, or None."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with _OPENER.open(request, timeout=timeout):
            return None
    except urllib.error.HTTPError as answer:
        if answer.code in (301, 302, 303, 307, 308):
            return answer.headers.get("Location")
        raise Unresolved(f"the link answered {answer.code}") from answer
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
        raise Unresolved(str(error)) from error


def resolve(url: str, get_location: LocationOf = location_of) -> str:
    """The map link a short link stands for. NotAShortLink for any other link; Unresolved when
    it cannot be followed to a map site's own link."""
    url = url.strip()
    if len(url) > MAX_URL or not is_short_link(url):
        raise NotAShortLink("not a short map link")
    current = url
    for _ in range(MAX_HOPS):
        target = get_location(current, TIMEOUT_S)
        if target is None:
            break
        target = urllib.parse.urljoin(current, target)
        if not _allowed_hop(target) or len(target) > MAX_URL:
            raise Unresolved("the link led off the map sites")
        current = target
        if not is_short_link(current):
            return current
    if is_short_link(current):
        raise Unresolved("the link did not lead to a map link")
    return current
