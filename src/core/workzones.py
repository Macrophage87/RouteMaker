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
- **Keeping.** One row of `core.models.BikeshareFeedCache` under the key `KEY`
  (`BikeshareFeedCache.WORKZONES`; the model says why it shares that table), replaced
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
import math
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

KEY = "workzones"  # its row in `bikeshare_feed_cache`: BikeshareFeedCache.WORKZONES
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
    except Exception as error:  # noqa: BLE001 - every failure is a FeedError
        # The reason's type only, whatever went wrong (a URLError, an SSL error, an
        # http.client IncompleteRead or InvalidURL): their text can repeat the URL,
        # and with it the key. One feed failing never stops the other's refresh.
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
    its last good zones and the time they were read. Returns a line for the run row.

    The copy is saved first, then the run fails (FeedError) when a configured feed's last
    good read is older than `STALE_AFTER_S`, or it has none (review OPS-3): a feed down
    for good used to leave every run a success while the planner called its zones stale,
    so nothing alerted. One failed tick inside the twenty minutes is not a failure."""
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
    line = "work zones: " + (", ".join(said) if said else "no feed configured")
    stale = []
    for source in wanted:
        when = rules._when(feeds[source].get("read_at"))
        if when is None or (now() - when).total_seconds() > STALE_AFTER_S:
            stale.append(source)
    if stale:
        raise FeedError(
            f"{line}; no good read in {STALE_AFTER_S / 60:.0f} minutes: {', '.join(stale)}"
        )
    return line


@dataclass(frozen=True)
class Snapshot:
    zones: tuple[rules.Zone, ...] = ()
    # source -> CURRENT, STALE or UNAVAILABLE, for every configured feed.
    status: dict[str, str] = field(default_factory=dict)
    read_at: dict[str, str | None] = field(default_factory=dict)
    # DC's park-level and text-only notices (`core.closure_sources`, v0.7.0).
    notices: tuple = ()


_lock = threading.Lock()
_cached: tuple[float, Snapshot] | None = None


def forget() -> None:
    global _cached
    with _lock:
        _cached = None


def _load(now: datetime) -> Snapshot:
    from . import closure_sources, reviewed_closures
    from .models import BikeshareFeedCache

    rows = {r.key: r for r in BikeshareFeedCache.objects.filter(key__in=[KEY, closure_sources.KEY])}
    zones: list[rules.Zone] = []
    notices: list = []
    status: dict[str, str] = {}
    read_at: dict[str, str | None] = {}
    # A row the worker has never written is a source not running here at all (a
    # checkout, or a deployment before its first refresh). Nothing is said of it.
    row = rows.get(KEY)
    if row is not None:
        payload = row.payload if isinstance(row.payload, dict) else {}
        feeds = payload.get("feeds") or {}
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
    row = rows.get(closure_sources.KEY)
    if row is not None:
        payload = row.payload if isinstance(row.payload, dict) else {}
        more, notices, more_status, more_read = closure_sources.load(payload, now)
        zones.extend(more)
        status.update(more_status)
        read_at.update(more_read)
    # The closures a reviewer entered or confirmed (v0.7.0; core.reviewed_closures): read from
    # their own table, so always current; named only while there are some. A failure to read
    # them leaves the feeds' zones in use.
    try:
        reviewed = reviewed_closures.zones(now)
    except Exception:  # noqa: BLE001 - the feeds' zones still stand
        logger.warning("reviewed closures could not be read", exc_info=True)
        reviewed = []
    if reviewed:
        zones.extend(reviewed)
        status[reviewed_closures.SOURCE] = CURRENT
        read_at[reviewed_closures.SOURCE] = now.isoformat()
    return Snapshot(tuple(zones), status, read_at, tuple(notices))


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


def plan_zones(points, when: str, now: datetime | None = None, bypass=()) -> rules.PlanZones | None:
    """The zones in force for a plan through `points` with the ride-time dial at `when`;
    None where work zones are not running (no refresh has ever been stored).

    Closures follow the ride, not today (v0.7.0): they are matched against the dial's
    moment, and one with no end given "may still apply" on a later ride and is not
    routed round. `bypass` names the closures the rider chose to route through."""
    found = snapshot()
    if not found.status:
        return None
    now = now or _now()
    plan = rules.for_plan(
        found.zones, ride_moment(when, now), points, found.status, now=now, bypass=bypass
    )
    plan.notices = list(found.notices)
    return plan


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


# --- The delay each closure makes (v0.7.0, "Closures on the map") ----------------------

# At most this many extra routes a plan asks to work out the closures' delays.
MAX_DELAY_ROUTES = 4


def _legs(answer) -> bool:
    return bool(((answer or {}).get("trip") or {}).get("legs"))


def measure_delays(
    answer: dict, request: dict, plan: rules.PlanZones | None, reroute, time_left_s
) -> None:
    """What each closure does to this route, and the time its detour adds.

    The closures the plan left out are asked again without them, once: those the route
    would then take are the ones that changed it (`plan.affecting`), and the time the
    way round adds is the difference. Where several did, each is asked alone. A closure
    the rider chose to route through is asked the other way: the time going round it
    would add. Each extra route needs `REROUTE_MIN_S` of the budget left, and at most
    `MAX_DELAY_ROUTES` are asked; a delay not worked out is None ("Your route goes round
    it"). `reroute(request) -> answer`; nothing here changes the route."""
    if plan is None or not _legs(answer):
        return
    base = _trip_time(answer["trip"])
    rings = list(request.get("exclude_polygons") or [])
    asked = 0

    def ask(polygons) -> dict | None:
        nonlocal asked
        if asked >= MAX_DELAY_ROUTES or time_left_s() < REROUTE_MIN_S:
            return None
        asked += 1
        trial = {k: v for k, v in request.items() if k not in ("exclude_polygons", "alternates")}
        if polygons:
            trial["exclude_polygons"] = polygons
        try:
            other = reroute(trial)
        except Exception as error:  # noqa: BLE001 - the delay is then not known
            logger.info("closures: a delay could not be worked out (%s)", type(error).__name__)
            return None
        return other if _legs(other) else None

    count = len(plan.excluded)
    if count and len(rings) >= count:
        free = ask(rings[count:])
        if free is not None:
            passing = rules.along(_trip_line(free["trip"]), plan.excluded)
            ids = list(dict.fromkeys(p.zone.zone_id for p in passing))
            plan.affecting = set(ids)
            if len(ids) == 1:
                plan.delays[ids[0]] = max(0.0, base - _trip_time(free["trip"]))
            else:
                for zone_id in ids:
                    index = next(i for i, z in enumerate(plan.excluded) if z.zone_id == zone_id)
                    other = ask(rings[:index] + rings[index + 1 :])
                    plan.delays[zone_id] = (
                        None if other is None else max(0.0, base - _trip_time(other["trip"]))
                    )
    if plan.bypassed:
        line = _trip_line(answer["trip"])
        for passage in rules.along(line, plan.bypassed):
            ring = rules.polygon(passage.zone)
            if ring is None:
                continue
            other = ask(rings + [ring])
            plan.delays[passage.zone.zone_id] = (
                None if other is None else max(0.0, _trip_time(other["trip"]) - base)
            )


# --- The route's words and the map's closures ----------------------------------------


def _entry(
    passage: rules.Passage | None,
    scale: float,
    text: str | None = None,
    stale: bool = False,
    note: str = "",
) -> dict:
    """A description entry (`routemaker.describe`'s shape), kind "workzone": a zone on
    the route at its metres scaled to the router's length, or, with no passage, a line
    at the start (the feeds that could not be read, a notice to check)."""
    at = 0.0 if passage is None else passage.from_m * scale
    to = 0.0 if passage is None else passage.to_m * scale
    zone = None if passage is None else passage.zone
    said = text
    if zone is not None:
        said = rules.heads_up(zone, at) + note + (stale_note(zone.source) if stale else "")
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
        "text": said,
        "text_lanes_hidden": None,
    }


STALE_NOTE = " This feed was last read more than 20 minutes ago."
BYPASS_NOTE = " You chose to route through it."
MAY_APPLY_NOTE = " No end time is given, so it may still apply on your ride day."


def stale_note(source: str) -> str:
    """The stale label for a source: the work zones' twenty minutes, or a DC source's own."""
    from . import closure_sources

    limit = closure_sources.STALE_AFTER_S.get(source)
    if limit is None:
        return STALE_NOTE
    minutes = round(limit / 60)
    span = f"{minutes // 60} hours" if minutes >= 120 else f"{minutes} minutes"
    return f" This source was last read more than {span} ago."


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
    names = [NAMES.get(s, s) for s, v in sorted(status.items()) if v == UNAVAILABLE]
    if not names:
        return None
    return f"Work zones could not be checked for this route: {' and '.join(names)} not available."


NAMES = {
    "md": "Maryland's feed",
    "va": "Virginia's feed",
    "dc": "DDOT's permits",
    "mpd": "MPD's traffic advisories",
    "alertdc": "AlertDC",
    "nps": "the NPS alerts",
    "reviewer": "the closures RouteMaker's reviewers confirmed",
}

# How near the route a closure in force is drawn on its map, metres (a closure further
# off has no effect worth showing).
MAP_NEAR_M = 400.0
# At most this many closures are drawn for a route, nearest first.
MAP_MOST = 60
# The kinds the map draws: closures in red, blocked bike lanes in amber. A rideable
# work zone with a penalty is a heads-up in the words, not a closure on the map.
MAP_KINDS = (rules.CLOSED, rules.UNKNOWN, rules.LANE)


def _near_line(zone: rules.Zone, coordinates, box) -> float:
    """How near the zone comes to the route's line, metres (inf beyond the box)."""
    if not any(box[0] <= lon <= box[2] and box[1] <= lat <= box[3] for lon, lat in zone.line):
        return math.inf
    lat0 = zone.line[0][1]
    route = [rules._xy(c[0], c[1], lat0) for c in coordinates]
    return min(rules._distance_to_line(rules._xy(lon, lat, lat0), route) for lon, lat in zone.line)


def _route_box(coordinates, margin_m: float):
    lons = [c[0] for c in coordinates]
    lats = [c[1] for c in coordinates]
    dlat = margin_m / 111_195.0
    dlon = dlat / max(math.cos(math.radians(sum(lats) / len(lats))), 0.01)
    return min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat


def _effect(zone: rules.Zone, plan: rules.PlanZones, on_route: set[str]) -> str:
    zone_id = zone.zone_id
    if any(z.zone_id == zone_id for z in plan.bypassed):
        return rules.BYPASSED
    if any(z.zone_id == zone_id for z in plan.uncertain):
        return rules.MAY_APPLY if zone_id in on_route else rules.NO_EFFECT
    if zone_id in on_route:
        return rules.ON_ROUTE
    if zone_id in plan.affecting:
        return rules.ROUTED_ROUND
    return rules.NO_EFFECT


def closure_row(
    zone: rules.Zone,
    effect: str,
    delay_s: float | None,
    now: datetime | None,
    future: bool,
    passage: rules.Passage | None = None,
    scale: float = 1.0,
) -> dict:
    """One closure as the map and its card show it (the API's `ClosureOut`)."""
    a = zone.line[(len(zone.line) - 1) // 2]
    b = zone.line[len(zone.line) // 2]
    middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return {
        "id": zone.zone_id,
        "source": zone.source,
        "source_name": rules.source_text(zone),
        "url": zone.url or rules.SOURCE_LINKS.get(zone.source),
        "kind": zone.kind,
        "severity": "amber" if zone.kind == rules.LANE else "red",
        "title": zone.title or _title(zone),
        "road": zone.road,
        "when_text": rules.when_text(zone, now, future),
        "start": None if zone.start is None else zone.start.isoformat(),
        "end": None if zone.end is None else zone.end.isoformat(),
        "effect": effect,
        "delay_s": None if delay_s is None else round(delay_s),
        "effect_text": rules.effect_text(zone, effect, delay_s),
        "can_bypass": zone.kind in (rules.CLOSED, rules.UNKNOWN),
        "bypassed": effect == rules.BYPASSED,
        "from_m": None if passage is None else round(passage.from_m * scale),
        "to_m": None if passage is None else round(passage.to_m * scale),
        "point": [round(middle[0], 6), round(middle[1], 6)],
        "line": [[round(p[0], 6), round(p[1], 6)] for p in zone.line],
    }


def _title(zone: rules.Zone) -> str:
    road = zone.road or "Road"
    if zone.kind == rules.LANE:
        return f"{road}: bike lane blocked"
    if zone.kind == rules.UNKNOWN:
        return f"{road}: every lane closed"
    return f"{road}: closed"


def notice_row(notice, now: datetime | None, future: bool) -> dict:
    """One "Check before you go" notice (the API's `ClosureNoticeOut`)."""
    from routemaker import dc_closures as dc

    area = dc.AREAS.get(notice.area)
    return {
        "id": notice.notice_id,
        "source": notice.source,
        "source_name": rules.SOURCES.get(notice.source, notice.source),
        "title": notice.title,
        "text": notice.text,
        "url": notice.url or (area.url if area else None),
        "area": notice.area,
        "area_name": area.name if area else None,
        "point": None if area is None or area.point is None else list(area.point),
        "category": notice.category,
        "when_text": dc.notice_when_text(notice, now, future),
    }


def map_rows(coordinates, plan: rules.PlanZones, passages, scale: float, now) -> list[dict]:
    """The closures to draw for a route: on it, or in force within `MAP_NEAR_M` of it."""
    if len(coordinates) < 2:
        return []
    on_route = {p.zone.zone_id: p for p in passages}
    box = _route_box(coordinates, MAP_NEAR_M)
    rows = []
    for zone in plan.every_zone():
        if zone.kind not in MAP_KINDS:
            continue
        near = 0.0 if zone.zone_id in on_route else _near_line(zone, coordinates, box)
        if near > MAP_NEAR_M:
            continue
        effect = _effect(zone, plan, set(on_route))
        row = closure_row(
            zone,
            effect,
            plan.delays.get(zone.zone_id),
            now,
            plan.future,
            on_route.get(zone.zone_id),
            scale,
        )
        rows.append((near, row))
    rows.sort(key=lambda r: (r[0], r[1]["id"]))
    return [row for _near, row in rows[:MAP_MOST]]


def with_work_zones(body: dict, plan: rules.PlanZones | None, now: datetime | None = None) -> dict:
    """The route's body with its work zones and closures: a heads-up in the description
    at each zone the route runs along, in route order, and `work_zones`, the summary (the
    zones on the route, how many it was routed round, each feed's status, the sources,
    the disclaimer, the closures to draw on its map and the "Check before you go"
    notices). `work_zones` is null where the plan read no zones."""
    if plan is None:
        body["work_zones"] = None
        return body
    from routemaker import avoid_junctions as geometry
    from routemaker import dc_closures as dc

    now = now or _now()
    coordinates = (body.get("geometry") or {}).get("coordinates") or []
    passages = rules.along(
        coordinates,
        [*plan.passable, *plan.unexcluded, *plan.bypassed, *plan.uncertain, *plan.lanes],
    )
    line_m = geometry.line_length_m(coordinates)
    scale = (body.get("distance_m") or 0.0) / line_m if line_m > 0 else 1.0
    bypassed = {z.zone_id for z in plan.bypassed}
    uncertain = {z.zone_id for z in plan.uncertain}

    def note(zone: rules.Zone) -> str:
        if zone.zone_id in bypassed:
            return BYPASS_NOTE
        if zone.zone_id in uncertain:
            return MAY_APPLY_NOTE
        return ""

    added = [
        _entry(p, scale, stale=plan.status.get(p.zone.source) == STALE, note=note(p.zone))
        for p in passages
    ]
    notices = []
    if plan.notices and plan.at is not None:
        notices = dc.notices_along(plan.notices, coordinates, plan.at)
    for notice in reversed(notices):
        said = f"Check before you go: {notice.title} ({rules.SOURCES.get(notice.source)})."
        if notice.url:
            said += f" {notice.url}"
        added.insert(0, _entry(None, scale, said))
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
                "text": rules.heads_up(p.zone, p.from_m * scale) + note(p.zone),
                "bypassed": p.zone.zone_id in bypassed,
                "may_still_apply": p.zone.zone_id in uncertain,
            }
            for p in passages
        ],
        "routed_round": len(plan.excluded) + len(plan.avoided),
        "status": dict(plan.status),
        "stale": [NAMES.get(s, s) for s in stale],
        "unchecked": unchecked,
        "sources": [rules.SOURCES[s] for s in sorted(plan.status) if s in rules.SOURCES],
        "disclaimer": rules.DISCLAIMER,
        "ride_at": None if plan.at is None else plan.at.isoformat(),
        "closures": map_rows(coordinates, plan, passages, scale, now),
        "notices": [notice_row(n, now, plan.future) for n in notices],
    }
    return body


# --- A kept line against the closures in force at the ride ---------------------------
#
# v0.7.0 plan, "GPX export as close to identical as possible, closure warning first", and its
# CORRECTION: a saved route, a shared link, an opened GPX or a plan left open keeps its line
# verbatim, so a closure that came in after it was planned is not routed round. When such a
# route is opened, on Start ride, and before a GPX download or a save, the page sends the line
# here and is told the closures it runs along, to offer "Reroute around them".
#
# The DC sources (v0.7.0 "DC closures source": DDOT permits, MPD, AlertDC, NPS) feed the same
# check: their closures are in the snapshot beside the work zones, and it is matched at the
# plan's ride time (its When dial) where the page sends one, not only now. A closure the rider
# chose to route through ("Route through anyway", for that plan) is not asked about again.


def _until_words(zone: rules.Zone, future: bool = False) -> str:
    if zone.end is None:
        if zone.source == "reviewer":
            return "until a reviewer ends it"
        if future:
            return "no end date given, so it may still apply on your ride day"
        return "no end date given"
    from routemaker import ridetime

    local = zone.end.astimezone(ridetime.ZONE)
    return f"until {local.strftime('%b')} {local.day}, {local.year}"


def _mi_km(metres: float) -> str:
    return f"{metres / 1609.344:.1f} mi ({metres / 1000:.1f} km)"


def closures_on(
    line,
    at: datetime | None = None,
    when: str | None = None,
    bypass=(),
    now: datetime | None = None,
) -> dict:
    """The closures in force at the ride that `line` runs along, in line order.

    The ride is `at`, else the plan's ride-time dial `when` (its next moment, as the
    planner matches it: `ride_moment`), else now. A closure is a work zone or DC closure
    closed to bicycles, or with every lane closed and bicycles not mentioned (the planner
    treats both as closures: `rules.severity` red). Each comes with its stretch along the
    line (`from_m`, `to_m`, on the line as sent) and one line of words: street, from and to
    along the route, until when. One with no end given, on a ride later than now, says it
    "may still apply" (`may_still_apply`). The ids in `bypass` are left out of `closures`
    and listed in `bypassed`.

    Additive to the dialog's first contract (v0.7.0): each closure's card fields (`title`,
    `source_key`, `source_name`, `url`, `when_text`, `line`), `lanes` (blocked bike lanes
    along the line: warnings, never closures), `notices` ("Check before you go": NPS park
    alerts and advisories that could not be placed) and `ride_at`.
    """
    from routemaker import dc_closures as dc

    found = snapshot()
    now = now or _now()
    moment = at or (ride_moment(when, now) if when else now)
    future = rules.is_future(moment, now)
    skip = set(bypass)
    zones = [z for z in found.zones if z.kind in MAP_KINDS and rules.active(z, moment)]
    passages = rules.along(line, zones) if zones else []
    closures, bypassed, lanes = [], [], []
    for p in passages:
        zone = p.zone
        uncertain = future and not zone.firm_end and zone.kind == rules.CLOSED
        road = zone.road or "A road with no name in the feed"
        row = {
            "id": zone.zone_id,
            "kind": zone.kind,
            "road": zone.road,
            "from_m": round(p.from_m),
            "to_m": round(p.to_m),
            "end": None if zone.end is None else zone.end.isoformat(),
            "source": rules.SOURCES.get(zone.source, zone.source),
            "text": (
                f"{road}, from {_mi_km(p.from_m)} to {_mi_km(p.to_m)} along the route,"
                f" {_until_words(zone, future)}."
            ),
            "may_still_apply": uncertain,
            "title": zone.title or _title(zone),
            "source_key": zone.source,
            "source_name": rules.source_text(zone),
            "url": zone.url or rules.SOURCE_LINKS.get(zone.source),
            "when_text": rules.when_text(zone, now, future),
            "line": [[round(c[0], 6), round(c[1], 6)] for c in zone.line],
        }
        if zone.kind == rules.LANE:
            lanes.append(row)
        elif zone.zone_id in skip:
            bypassed.append(row)
        else:
            closures.append(row)
    notices = dc.notices_along(found.notices, line, moment) if found.notices else []
    return {
        "closures": closures,
        "unchecked": unchecked_text(found.status) if found.status else None,
        "ride_at": moment.isoformat(),
        "bypassed": bypassed,
        "lanes": lanes,
        "notices": [notice_row(n, now, future) for n in notices],
    }
