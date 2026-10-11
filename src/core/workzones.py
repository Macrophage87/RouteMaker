"""The live work-zone feeds: fetched by the worker, kept as one shared copy, read by the planner.

FOLLOWUP-WORKZONES (OWNER-DECISIONS 341-349). `routemaker.workzones` reads the
feeds; this module is the part that touches the network and the database.

- **Fetching.** The worker's `refresh_work_zones` task (config.procrastinate, every
  `REFRESH_MINUTES` minutes: 346's "about 5 min, without overburdening the feed")
  calls `refresh()`, which reads each configured feed with up to `TRIES` tries, and
  keeps the last good copy of a feed that fails. Maryland needs no key. Virginia's
  feed needs the owner's SmarterRoads key, read from the environment variable
  `SMARTERROADS_TOKEN` on the worker only (346: "the key stays server-side only");
  without it Virginia is off and nothing is asked of VDOT. The key is never logged:
  every message names the feed, not its URL.
- **Keeping.** One row of `core.models.BikeshareFeedCache` under the key `KEY`, replaced
  at each refresh: the zones as parsed (not the raw feed), when each feed was last
  read, and whether its last read failed. No history is kept; the table is left out of
  the nightly dump and refills itself.
- **Reading.** The planner asks `snapshot()`, which reads that row at most once every
  `READ_TTL_S` seconds a process. A feed read within `STALE_AFTER_S` is current;
  within `DROP_AFTER_S` it is used and labelled stale; older, or never read, its
  zones are not used and the planner says work zones there could not be checked
  (346: "if the feed is suspended, the planner labels it unavailable").
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from routemaker import workzones as rules

logger = logging.getLogger(__name__)

KEY = "workzones"
REFRESH_MINUTES = 5
TRIES = 3
RETRY_WAIT_S = 2.0
TIMEOUT_S = 20.0
MAX_BYTES = 30_000_000
STALE_AFTER_S = 20 * 60.0
DROP_AFTER_S = 2 * 60 * 60.0
READ_TTL_S = 60.0
USER_AGENT = "RouteMaker-work-zones"
TOKEN_ENV = "SMARTERROADS_TOKEN"

# The WZDx Feed Registry's entries (datahub.transportation.gov, read 2026-10-11):
# Maryland's v4.1 feed, public, refreshed every minute; VDOT's v4 feed through
# SmarterRoads, which takes the subscriber's key as `token`.
FEEDS = {
    "md": "https://filter.ritis.org/wzdx_v4.1/mdot.geojson",
    "va": (
        "https://data.511-atis-ttrip-prod.iteriscloud.com/smarterRoads/workzone/"
        "workZoneJSON/current/workZone.json"
    ),
}
NEEDS_TOKEN = frozenset({"va"})
PUBLIC = frozenset(FEEDS) - NEEDS_TOKEN

CURRENT, STALE, UNAVAILABLE = "current", "stale", "unavailable"

Fetch = Callable[[str, float], bytes]


class FeedError(Exception):
    """A feed could not be read; the message never carries the URL or the key."""


def token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def configured() -> dict[str, str]:
    """The feeds to read, with their URLs (the key added where one is needed)."""
    out = {}
    for source, url in FEEDS.items():
        if source in NEEDS_TOKEN:
            key = token()
            if not key:
                continue
            url = f"{url}?{urllib.parse.urlencode({'token': key})}"
        out[source] = url
    return out


def http_get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise FeedError(f"HTTP {error.code}") from None
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
        # The reason only: a URLError's text can repeat the URL, and with it the key.
        raise FeedError(type(error).__name__) from None
    if len(body) > MAX_BYTES:
        raise FeedError("larger than expected")
    return body


def read_feed(source: str, url: str, fetch: Fetch = http_get, sleep=time.sleep) -> list[rules.Zone]:
    """One feed's zones, with up to `TRIES` tries."""
    last: Exception | None = None
    for attempt in range(TRIES):
        if attempt:
            sleep(RETRY_WAIT_S * attempt)
        try:
            return rules.parse_feed(json.loads(fetch(url, TIMEOUT_S)), source)
        except (FeedError, ValueError) as error:
            last = error
    raise FeedError(f"{source}: {last}")


def _now() -> datetime:
    return datetime.now(UTC)


def refresh(fetch: Fetch = http_get, sleep=time.sleep, now: Callable[[], datetime] = _now) -> str:
    """Read every configured feed and replace the shared copy. A feed that fails keeps
    its last good zones and the time they were read. Returns a line for the run row."""
    from .models import BikeshareFeedCache

    row = BikeshareFeedCache.objects.filter(key=KEY).first()
    payload = row.payload if row is not None and isinstance(row.payload, dict) else {}
    feeds = dict(payload.get("feeds") or {})
    said = []
    wanted = configured()
    for source in list(feeds):
        if source not in wanted:
            del feeds[source]  # Virginia's key removed: its zones go with it
    for source, url in wanted.items():
        try:
            zones = read_feed(source, url, fetch, sleep)
        except FeedError as error:
            logger.warning("work zones: the %s feed could not be read (%s)", source, error)
            kept = feeds.get(source) or {}
            feeds[source] = {**kept, "failed_at": now().isoformat()}
            said.append(f"{source} failed")
            continue
        feeds[source] = {
            "read_at": now().isoformat(),
            "failed_at": None,
            "zones": [zone.to_json() for zone in zones],
        }
        said.append(f"{source} {len(zones)} zones")
    BikeshareFeedCache.objects.update_or_create(
        key=KEY,
        defaults={"payload": {"feeds": feeds}, "fetched_at": now(), "failed_at": None},
    )
    forget()
    return "work zones: " + (", ".join(said) if said else "no feed configured")


@dataclass(frozen=True)
class Snapshot:
    zones: tuple[rules.Zone, ...] = ()
    # source -> CURRENT, STALE or UNAVAILABLE, for every configured feed.
    status: dict[str, str] = field(default_factory=dict)
    read_at: dict[str, str | None] = field(default_factory=dict)


_lock = threading.Lock()
_cached: tuple[float, Snapshot] | None = None


def forget() -> None:
    global _cached
    with _lock:
        _cached = None


def _load(now: datetime) -> Snapshot:
    from .models import BikeshareFeedCache

    row = BikeshareFeedCache.objects.filter(key=KEY).first()
    if row is None:
        # The worker has never refreshed: work zones are not running here at all (a
        # checkout, or a deployment before its first refresh). Nothing is said.
        return Snapshot()
    payload = row.payload if isinstance(row.payload, dict) else {}
    feeds = payload.get("feeds") or {}
    zones: list[rules.Zone] = []
    status: dict[str, str] = {}
    read_at: dict[str, str | None] = {}
    # The feeds the worker reads: Maryland always, Virginia where the worker has the
    # key (the API does not hold it, so it goes by what the worker stored).
    for source in sorted(set(feeds) | PUBLIC):
        feed = feeds.get(source) or {}
        when = rules._when(feed.get("read_at"))
        read_at[source] = feed.get("read_at")
        age = None if when is None else (now - when).total_seconds()
        if age is None or age > DROP_AFTER_S:
            status[source] = UNAVAILABLE
            continue
        status[source] = CURRENT if age <= STALE_AFTER_S else STALE
        for row_zone in feed.get("zones") or []:
            try:
                zones.append(rules.Zone.from_json(row_zone))
            except (KeyError, TypeError, ValueError):
                continue
    return Snapshot(tuple(zones), status, read_at)


def snapshot(now: datetime | None = None) -> Snapshot:
    """The zones the planner may use, and each feed's status. Never raises: a database
    error is a snapshot with every feed unavailable."""
    global _cached
    clock = time.monotonic()
    with _lock:
        if _cached is not None and clock - _cached[0] < READ_TTL_S:
            return _cached[1]
    try:
        found = _load(now or _now())
    except Exception:  # noqa: BLE001 - a plan is answered without work zones
        logger.warning("work zones could not be read", exc_info=True)
        found = Snapshot(status=dict.fromkeys(PUBLIC, UNAVAILABLE))
    with _lock:
        _cached = (clock, found)
    return found


# --- The planner's side ----------------------------------------------------------

# Seconds of the plan's budget a re-route round penalty zones needs, at least.
REROUTE_MIN_S = 4.0


def ride_moment(when: str, now: datetime | None = None) -> datetime:
    """The moment the plan's ride is taken to start, for the zones' windows: now, where
    the ride-time dial is on the setting of the moment (a ride planned to go now);
    otherwise the dial's next representative instant, as the router is asked
    (`routemaker.ridetime.representative_time`)."""
    from routemaker import ridetime

    now = now or _now()
    if ridetime.when_at(now) == when:
        return now
    local = datetime.fromisoformat(ridetime.representative_time(when, now))
    return local.replace(tzinfo=ridetime.ZONE).astimezone(UTC)


def plan_zones(points, when: str, now: datetime | None = None) -> rules.PlanZones | None:
    """The zones in force for a plan through `points` with the ride-time dial at `when`;
    None where work zones are not running (no refresh has ever been stored)."""
    found = snapshot()
    if not found.status:
        return None
    return rules.for_plan(found.zones, ride_moment(when, now), points, found.status)


def _trip_line(trip: dict) -> list[tuple[float, float]]:
    from routemaker import trace_junctions

    line: list[tuple[float, float]] = []
    for leg in trip.get("legs") or []:
        shape = trace_junctions.decode_polyline6(leg.get("shape", ""))
        line.extend(shape[1:] if line else shape)
    return line


def _trip_time(trip: dict) -> float:
    return float((trip.get("summary") or {}).get("time") or 0.0)


def drop_exclusions(request: dict, plan: rules.PlanZones) -> None:
    """Take the closures out of the request, where the router found no route round them:
    they are then warned of on the route as closures that could not be left out."""
    request.pop("exclude_polygons", None)
    plan.unexcluded.extend(plan.excluded)
    plan.excluded = []
    plan.exclude = []


def settle_penalties(answer: dict, request: dict, plan: rules.PlanZones, reroute, time_left_s):
    """Where the router's route runs along zones with a penalty, ask once for the route
    with them left out as well, and keep it where its time is no more than the first
    route's time plus their penalties (342(4): a penalty, not an exclusion). Returns the
    answer to use; the request then carries the zones left out, so every later search
    leaves them out too, and `plan.avoided` names them.

    `reroute(request) -> answer` asks the router; `time_left_s()` is the budget left.
    A refusal or a missed budget keeps the first route."""
    if not plan.passable:
        return answer
    trip = answer.get("trip") or {}
    line = _trip_line(trip)
    passages = rules.along(line, plan.passable)
    if not passages or time_left_s() < REROUTE_MIN_S:
        return answer
    used_m, used_vertices = rules.budget_used(plan.exclude)
    zones = list({p.zone.zone_id: p.zone for p in passages}.values())
    centre = line[len(line) // 2]
    rings, fitted, _left = rules.fit_polygons(zones, centre, used_m, used_vertices)
    if not rings:
        return answer
    trial = {**request, "exclude_polygons": list(plan.exclude) + rings}
    try:
        other = reroute(trial)
    except Exception as error:  # noqa: BLE001 - the first route stands
        logger.info("work zones: no route round the penalty zones (%s)", type(error).__name__)
        return answer
    penalty = sum(zone.penalty_s for zone in fitted)
    if not (other.get("trip") or {}).get("legs"):
        return answer
    if _trip_time(other["trip"]) > _trip_time(trip) + penalty:
        return answer
    request["exclude_polygons"] = trial["exclude_polygons"]
    plan.exclude = trial["exclude_polygons"]
    plan.avoided = fitted
    return other


def _entry(
    passage: rules.Passage | None, scale: float, text: str | None = None, stale: bool = False
) -> dict:
    """A description entry (`routemaker.describe`'s shape), kind "workzone": a zone on
    the route at its metres scaled to the router's length, or, with no passage, a line
    at the start (the feeds that could not be read)."""
    at = 0.0 if passage is None else passage.from_m * scale
    to = 0.0 if passage is None else passage.to_m * scale
    zone = None if passage is None else passage.zone
    return {
        "kind": "workzone",
        "from_m": round(at),
        "to_m": round(to),
        "from_mi": round(at / 1609.344, 2),
        "to_mi": round(to / 1609.344, 2),
        "street": None if zone is None else zone.road,
        "tier": None,
        "facility": None,
        "turn": None,
        "severity": None if zone is None else rules.severity(zone),
        "via": None,
        "group": None,
        "surface": None,
        "text": text if zone is None else rules.heads_up(zone, at) + (STALE_NOTE if stale else ""),
        "text_lanes_hidden": None,
    }


STALE_NOTE = " This feed was last read more than 20 minutes ago."


def _merge(description: list[dict] | None, added: list[dict]) -> list[dict] | None:
    """The description with `added` in route order, each before the entry that starts
    where it is; None stays None."""
    if description is None or not added:
        return description
    out: list[dict] = []
    pending = sorted(added, key=lambda e: e["from_m"])
    for entry in description:
        while pending and pending[0]["from_m"] <= entry["from_m"]:
            out.append(pending.pop(0))
        out.append(entry)
    out.extend(pending)
    return out


def unchecked_text(status: dict[str, str]) -> str | None:
    """'Work zones could not be checked ...' for the feeds not in use; None where all are."""
    names = [NAMES[s] for s, v in sorted(status.items()) if v == UNAVAILABLE]
    if not names:
        return None
    return f"Work zones could not be checked for this route: {' and '.join(names)} not available."


NAMES = {"md": "Maryland's feed", "va": "Virginia's feed"}


def with_work_zones(body: dict, plan: rules.PlanZones | None) -> dict:
    """The route's body with its work zones: a heads-up in the description at each zone
    the route runs along, in route order, and `work_zones`, the summary (the zones on the
    route, how many it was routed round, each feed's status, the sources and the
    disclaimer). `work_zones` is null where the plan read no zones."""
    if plan is None:
        body["work_zones"] = None
        return body
    from routemaker import avoid_junctions as geometry

    coordinates = (body.get("geometry") or {}).get("coordinates") or []
    passages = rules.along(coordinates, [*plan.passable, *plan.unexcluded])
    line_m = geometry.line_length_m(coordinates)
    scale = (body.get("distance_m") or 0.0) / line_m if line_m > 0 else 1.0
    added = [_entry(p, scale, stale=plan.status.get(p.zone.source) == STALE) for p in passages]
    unchecked = unchecked_text(plan.status)
    if unchecked:
        added.insert(0, _entry(None, scale, unchecked))
    if passages:
        added.insert(0, _entry(None, scale, rules.DISCLAIMER))
    for key in ("description", "description_overview"):
        body[key] = _merge(body.get(key), added)
    stale = sorted(s for s, v in plan.status.items() if v == STALE)
    body["work_zones"] = {
        "on_route": [
            {
                "id": p.zone.zone_id,
                "kind": p.zone.kind,
                "penalty_s": p.zone.penalty_s,
                "road": p.zone.road,
                "description": p.zone.description,
                "reason": p.zone.reason,
                "from_m": round(p.from_m * scale),
                "to_m": round(p.to_m * scale),
                "start": None if p.zone.start is None else p.zone.start.isoformat(),
                "end": None if p.zone.end is None else p.zone.end.isoformat(),
                "source": p.zone.source,
                "warning": p.zone.kind in (rules.CLOSED, rules.UNKNOWN),
                "text": rules.heads_up(p.zone, p.from_m * scale),
            }
            for p in passages
        ],
        "routed_round": len(plan.excluded) + len(plan.avoided),
        "status": dict(plan.status),
        "stale": [NAMES[s] for s in stale],
        "unchecked": unchecked,
        "sources": [rules.SOURCES[s] for s in sorted(plan.status)],
        "disclaimer": rules.DISCLAIMER,
    }
    return body
