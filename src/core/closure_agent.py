"""The closure agent: the agencies' closure pages read by Claude, on the server (v0.31.0).

The owner, 2026-11-28: "build it now, as if this computer is off, then it would stop. Durability
is more useful", and "Should we expand further than just those 3 agencies? there's a bunch",
"Roadway too". The agencies below post their trail and road closures only as words on a page,
with no feed: the feeds that exist (DDOT, MPD, AlertDC, NPS, SHA, MoCo, the work zones) have
their own readers (`core.closure_sources`, `core.workzones`).

- **Reading.** Every hour (config.procrastinate `run_closure_agent`) each page in `SOURCES` is
  read and made plain text. Only a page whose text changed since the last read is sent to Claude
  (`ask`), which lists the closures it states that close one named way, trail or road, between
  two places on it, with their days where the page gives them (`SCHEMA`). An unchanged page costs
  nothing; at most `CALLS_PER_DAY` asks a day. The page is the evidence: only what it says.
- **Placing.** Each closure is drawn along its way between its two places from OpenStreetMap
  (`routemaker.osm_place.between`; the C&O towpath by its mileposts, `park_alerts.towpath_lines`).
  What cannot be drawn is left out and counted in the run line: never guessed.
- **Closing.** Each drawn closure is an agent closure (`core.reviewed_closures`, "Agent
  closures", the owner's rule of 2026-11-28: any alert that can be placed goes in, dated or not,
  and ends when the agency drops it): entered with `agent_key` `a:SOURCE:HASH`, its last day the
  page's, or, with none, today only, moved on a day at each read while the page still lists it,
  and ended at the first read that does not. A page that could not be read changes nothing, so
  an undated closure lapses on its own within a day. The agent writes as no account
  (`reviewed_closures.WORKER`).
- **Off** where the worker has no Claude credentials: the Workload Identity Federation variables
  (`ANTHROPIC_FEDERATION_RULE_ID` and the rest, the SDK's own) or `ANTHROPIC_API_KEY`. The SDK
  reads them; nothing here does, and none is written anywhere.

Kept in one `BikeshareFeedCache` row (`KEY`): each page's text, its hash and the closures last
drawn from it (public pages only, nothing personal). A changed page is screened by Claude Haiku
first (`screen`): Opus reads it only where a closure may have changed. docs/OPERATIONS.md, "The closure agent".
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

from django.utils import timezone

from routemaker import osm_place
from routemaker import park_alerts as pa

from . import reviewed_closures as rc
from . import stress_edits
from .models import BikeshareFeedCache, ReviewedClosure

log = logging.getLogger(__name__)

KEY = "closure_agent"
# Claude Opus 5.5, the current default model; low effort, as reading a page is plain extraction.
MODEL = "claude-opus-5-5"
EFFORT = "low"
# The screen (the owner, 2026-11-28: "What about haiku to test if there is a change then opus to
# describe them?"): Claude Haiku 5.5 is shown what changed on a page since Opus last read it and
# says whether any closure may have changed. Only then is Opus asked, so a page's clock or banner
# costs a fraction of a cent, not an Opus read. A page Opus has not read for `RECHECK_DAYS` is
# read again whatever the screen says, in case the screen missed one: our default, unmeasured.
SCREEN_MODEL = "claude-haiku-5-5"
SCREEN_DIFF_CHARS_MAX = 20_000
RECHECK_DAYS = 1
MAX_TOKENS = 16000
# At most this many asks a day, all pages together (about $0.05 each): our default, unmeasured,
# sized to stay well inside the owner's $200 a month of credits.
CALLS_PER_DAY = 120
# A page's text past this is cut (and the run line says so): our default.
PAGE_CHARS_MAX = 60_000
FETCH_TIMEOUT_S = 30
# One ask waits at most this long, tried at most twice, so a pass fits its 15-minute deadline.
ASK_TIMEOUT_S = 120.0
# A page's text that failed this many asks is asked again only once the page changes.
ASK_TRIES = 3
# Nominatim's usage policy: at most one search a second.
SEARCH_GAP_S = 1.1
USER_AGENT = "RouteMaker-closures"


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    page: str
    area: str  # where its places are, for the map search ("Fairfax County, Virginia")


# The pages. The first three are the ones the person-read watch has followed since v0.26.0; the
# rest were found on 2026-11-28 to list closures as text. Baltimore County's and Laurel's answered
# the beta's worker 403 that day (their bot screens): the run line names a page that cannot be
# read. Arlington's long-term traffic alerts are left out: its site refuses the beta's address.
SOURCES = (
    Source("nova", "NOVA Parks", pa.NOVA.page, "Virginia"),
    Source("choh", "NPS, C&O Canal", pa.CHOH.page, "Maryland"),
    Source("aacounty", pa.AACOUNTY.name, pa.AACOUNTY.page, "Anne Arundel County, Maryland"),
    Source(
        "fcpa",
        "Fairfax County Park Authority",
        "https://www.fairfaxcounty.gov/parks/park-alerts",
        "Fairfax County, Virginia",
    ),
    Source(
        "mcparks",
        "Montgomery Parks",
        "https://www.montgomeryparks.org/activities/park-trails/rainoutline-trails-operating-status/",
        "Montgomery County, Maryland",
    ),
    Source(
        "rocr",
        "NPS, Rock Creek Park",
        "https://www.nps.gov/rocr/planyourvisit/conditions.htm",
        "Washington, DC",
    ),
    Source(
        "baltco",
        "Baltimore County Public Works",
        "https://www.baltimorecountymd.gov/departments/publicworks/roadclosures",
        "Baltimore County, Maryland",
    ),
    Source(
        "laurel",
        "City of Laurel",
        "https://laurelmd.gov/1620/Current-Road-Closures",
        "Laurel, Maryland",
    ),
)
BY_KEY = {s.key: s for s in SOURCES}

SYSTEM = """You read one public agency's page of closures for a bicycle route planner.

List each closure the page states that closes one named way (a trail, path, towpath or road) to
people on bicycles between two places on that way, so the planner can route round it. A road
closed to traffic counts; a lane closure, a closed building, parking lot, field or programme does
not. A detour counts as a closure of the way it takes riders off.

For each closure give:
- way: the way's name as the page writes it ("W&OD Trail", "B&A Trail", "Fourth Street").
- from_place and to_place: the two cross streets or places on the way that bound the closed part,
  as the page names them. Where the page gives only one place, or none, leave the closure out.
- mileposts: for the C&O Canal towpath, the two mileposts that bound it (e.g. [4.7, 5.2]);
  otherwise [].
- first_day and last_day: the days the page gives, as YYYY-MM-DD, or "" where it gives none.
  Use today's date (given below) to place a day the page writes without a year.
- reason: why it is closed, in a few plain words ("tree down", "bridge repair").

Leave out any closure whose last day is before today. A closure the page dated months ago with no
last day is most likely over: leave it out unless the page says it is still in force. Use only what
the page says: never a guess, another source or what is usual. An empty list is a fine answer."""

SCHEMA = {
    "type": "object",
    "properties": {
        "closures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "way": {"type": "string"},
                    "from_place": {"type": "string"},
                    "to_place": {"type": "string"},
                    "mileposts": {"type": "array", "items": {"type": "number"}},
                    "first_day": {"type": "string"},
                    "last_day": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "way",
                    "from_place",
                    "to_place",
                    "mileposts",
                    "first_day",
                    "last_day",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["closures"],
    "additionalProperties": False,
}


def credentials() -> bool:
    """Whether the worker has Claude credentials the SDK will use (their names only)."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return True
    federation = ("ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID")
    token = ("ANTHROPIC_IDENTITY_TOKEN_FILE", "ANTHROPIC_IDENTITY_TOKEN")
    return all(os.environ.get(n, "").strip() for n in federation) and any(
        os.environ.get(n, "").strip() for n in token
    )


# --- Reading ------------------------------------------------------------------------------


def http_get(url: str) -> str:
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as answer:  # noqa: S310
        return answer.read(4_000_000).decode("utf-8", "replace")


_DROP = re.compile(r"(?is)<(script|style|noscript|svg|nav|header|footer)\b.*?</\1>")
_BREAK = re.compile(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr|/section|/article)\b[^>]*>")


def page_text(page: str) -> str:
    """The page's words, a line a block, without its scripts, menus and footer."""
    page = _BREAK.sub("\n", _DROP.sub(" ", page))
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def read(source: Source, get=http_get) -> str:
    """The text Claude reads for one source. The three watched agencies' items as their tested
    readers give them (NOVA's alerts are a page each, linked from its home page); the rest, the
    page's text."""
    if source.key == "nova":
        items = []
        for url in pa.nova_links(get(pa.NOVA.page)):
            item = pa.nova_item(url, get(url))
            if item is not None:
                items.append(item)
    elif source.key == "choh":
        items = pa.choh_items(get(pa.CHOH.page))
    elif source.key == "aacounty":
        items = pa.aacounty_items(get(pa.AACOUNTY.page))
    else:
        return page_text(get(source.page))
    return "\n\n".join(f"{i.place}: {i.text} ({i.link})" for i in items)


# --- Asking Claude ------------------------------------------------------------------------


SCREEN_SYSTEM = """You compare two readings of one public agency's closures page for a bicycle route
planner. You are shown the lines that changed. Answer true if the change could add, remove or
alter a closure of a trail, path or road (its place, its days, or whether it is closed), and false
if it cannot (a clock, a date stamp, a banner, an event, a menu). When unsure, answer true."""

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {"closure_change": {"type": "boolean"}},
    "required": ["closure_change"],
    "additionalProperties": False,
}


def changed_lines(before: str, after: str) -> str:
    """The lines that differ between two readings, as a unified diff."""
    import difflib

    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=1)
    return "\n".join(list(lines)[2:])[:SCREEN_DIFF_CHARS_MAX]


def _client(client):
    if client is not None:
        return client
    import anthropic

    # Well inside the run's deadline (config.procrastinate CLOSURE_AGENT_TIMEOUT_S).
    return anthropic.Anthropic(timeout=ASK_TIMEOUT_S, max_retries=1)


def screen(source: Source, diff: str, client=None) -> bool:
    """Whether the change may touch a closure (Haiku). True where it cannot tell."""
    response = _client(client).messages.create(
        model=SCREEN_MODEL,
        max_tokens=2000,
        system=SCREEN_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"{source.name}, {source.page}:\n\n<changes>\n{diff}\n</changes>",
            }
        ],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCREEN_SCHEMA}},
    )
    if response.stop_reason != "end_turn":
        return True
    answer = [b.text for b in response.content if b.type == "text"][-1]
    return bool(json.loads(answer).get("closure_change", True))


def ask(source: Source, text: str, today: date, client=None) -> list[dict]:
    """The closures Claude finds on the page (`SCHEMA`)."""
    response = _client(client).beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Today is {today.isoformat()}. The page is {source.name}'s, {source.page}:"
                    f"\n\n<page>\n{text}\n</page>"
                ),
            }
        ],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if response.stop_reason != "end_turn":
        raise ValueError(f"the reading stopped ({response.stop_reason})")
    # The last text: where one model declined and another went on, the answer is the second's.
    answer = [b.text for b in response.content if b.type == "text"][-1]
    return list(json.loads(answer).get("closures") or [])


# --- Placing ------------------------------------------------------------------------------


def _day(value) -> str:
    value = str(value or "").strip()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def alert_key(source: Source, found: dict) -> str:
    """The closure's key: its source and a hash of its way and places, so the same closure read
    again is the same key however the page's words around it change."""
    parts = [found.get("way"), found.get("from_place"), found.get("to_place")]
    words = "|".join(" ".join(str(p or "").lower().split()) for p in parts)
    return f"a:{source.key}:{hashlib.sha256(words.encode()).hexdigest()[:12]}"


def place(source: Source, found: dict, get_json) -> list[list] | None:
    """The closure's lines, or None where it cannot be drawn. A failed map read raises."""
    way = str(found.get("way") or "").strip()
    miles = [float(m) for m in found.get("mileposts") or [] if isinstance(m, int | float)]
    if source.key == "choh" and len(miles) == 2:
        return pa.towpath_lines(min(miles), max(miles)) or None
    first = str(found.get("from_place") or "").strip()
    second = str(found.get("to_place") or "").strip()
    if not (way and first and second):
        return None
    try:
        return [osm_place.between(way, first, second, source.area, get_json)]
    except osm_place.NotClear:
        return None


def drawn(
    source: Source, found: list[dict], get_json, before: list[dict] | None = None
) -> tuple[list[dict], int, int]:
    """Each closure Claude found that can be drawn, ready to enter; how many could not be drawn;
    and how many the map could not be read for (each of those keeps its line from `before`, the
    last drawing, where it has one, and is drawn again at the next read)."""
    old = {item["key"]: item for item in before or []}
    out, missed, unread = [], 0, 0
    for item in found:
        key = alert_key(source, item)
        try:
            lines = place(source, item, get_json)
        except Exception as error:  # noqa: BLE001 - a refused or failed map read
            log.info("closure agent: %s %s: the map could not be read (%s)", source.key, key, error)
            unread += 1
            if key in old:
                out.append(dict(old[key], redraw=True))
            continue
        if not lines:
            missed += 1
            continue
        way = " ".join(str(item.get("way") or "").split())[:120]
        why = " ".join(str(item.get("reason") or "").split())[:160]
        out.append(
            {
                "key": key,
                "lines": lines,
                "reason": f"{way} closed{': ' + why if why else ''} ({source.name})",
                "first_day": _day(item.get("first_day")),
                "last_day": _day(item.get("last_day")),
            }
        )
    return out, missed, unread


def _osm_getter(sleep=time.sleep):
    last = [0.0]

    def get_json(url: str):
        if url.startswith(osm_place.NOMINATIM):
            wait = SEARCH_GAP_S - (time.monotonic() - last[0])
            if wait > 0:
                sleep(wait)
            last[0] = time.monotonic()
        return json.loads(http_get(url))

    return get_json


# --- Closing ------------------------------------------------------------------------------


def apply(source: Source, wanted: list[dict], today: date) -> dict:
    """Enter, extend and end this source's agent closures so they match `wanted`. A key a person
    ended (from the road panel's list) is not entered again: the person's word stands."""
    counts = {"entered": 0, "extended": 0, "ended": 0, "refused": 0}
    prefix = f"a:{source.key}:"
    mine = ReviewedClosure.objects.filter(agent_key__startswith=prefix, created_by__isnull=True)
    live = {c.agent_key: c for c in rc.live_rows().filter(pk__in=mine.values("pk"))}
    dismissed = set(
        mine.filter(ended_by__isnull=False).values_list("agent_key", flat=True)
    )  # fmt: skip
    keep: set[str] = set()
    for item in wanted:
        last = item["last_day"]
        if last and date.fromisoformat(last) < today:
            continue
        for n, line in enumerate(item["lines"], start=1):
            key = f"{item['key']}:{n}"
            keep.add(key)
            if key in dismissed and key not in live:
                continue
            try:
                if key in live:
                    before = live[key].end
                    closure = rc.extend(rc.WORKER, live[key].pk, last or None)
                    counts["extended"] += closure.end != before
                else:
                    rc.create(
                        rc.WORKER,
                        line=line,
                        reason=item["reason"],
                        start=item["first_day"] or None,
                        end=last or None,
                        url=source.page,
                        agent_key=key,
                    )
                    counts["entered"] += 1
            except stress_edits.EditRefused as why:
                log.info("closure agent: %s %s refused: %s", source.key, key, why)
                counts["refused"] += 1
    for key, closure in live.items():
        if key not in keep:
            rc.end_now(rc.WORKER, closure.pk)
            counts["ended"] += 1
    return counts


# --- The hourly run -----------------------------------------------------------------------


def _state() -> dict:
    row = BikeshareFeedCache.objects.filter(key=KEY).first()
    return dict(row.payload or {}) if row and isinstance(row.payload, dict) else {}


def _save(state: dict) -> None:
    BikeshareFeedCache.objects.update_or_create(
        key=KEY, defaults={"payload": state, "fetched_at": timezone.now()}
    )


def run(get=http_get, get_json=None, client=None, now: datetime | None = None) -> str:
    """One hourly pass over every source; returns the run line."""
    if client is None and not credentials():
        return "off: the worker has no Claude credentials"
    get_json = get_json or _osm_getter()
    now = now or timezone.now()
    today = now.astimezone(rc._zone_info()).date()
    state = _state()
    pages = dict(state.get("pages") or {})
    calls = state.get("calls") or {}
    used = int(calls.get("n") or 0) if calls.get("day") == today.isoformat() else 0
    totals = {"entered": 0, "extended": 0, "ended": 0, "refused": 0}
    asked = missed = unread = read_ok = screened = 0
    failed, cut, capped = [], [], []
    # A different page first each hour, so a spent allowance does not always fall on the last.
    turn = now.hour % len(SOURCES)
    for source in SOURCES[turn:] + SOURCES[:turn]:
        try:
            text = read(source, get)
        except Exception as error:  # noqa: BLE001 - a page that fails changes nothing
            failed.append(f"{source.key} ({type(error).__name__})")
            continue
        read_ok += 1
        if len(text) > PAGE_CHARS_MAX:
            text = text[:PAGE_CHARS_MAX]
            cut.append(source.key)
        digest = hashlib.sha256(text.encode()).hexdigest()
        kept = dict(pages.get(source.key) or {})
        redraw = any(item.get("redraw") for item in kept.get("closures") or [])
        if kept.get("hash") != digest:
            tries = int(kept.get("tries") or 0) if kept.get("asking") == digest else 0
            read_on = kept.get("read_on") or ""
            fresh = bool(read_on) and (today - date.fromisoformat(read_on)).days < RECHECK_DAYS
            quiet = False
            if fresh and kept.get("text"):
                try:
                    quiet = not screen(source, changed_lines(kept["text"], text), client)
                except Exception as error:  # noqa: BLE001 - Opus reads it instead
                    log.info("closure agent: %s screen failed (%s)", source.key, error)
                screened += 1
            if quiet:
                kept.update(hash=digest, text=text)  # no closure changed: nothing to ask
            elif used >= CALLS_PER_DAY:
                capped.append(source.key)
            elif tries >= ASK_TRIES:
                pass  # this text failed every try: asked again when the page changes
            else:
                used += 1
                try:
                    found = ask(source, text, today, client)
                except Exception as error:  # noqa: BLE001 - asked again next hour
                    failed.append(f"{source.key} (asking: {type(error).__name__})")
                    kept.update(asking=digest, tries=tries + 1)
                    found = None
                if found is not None:
                    asked += 1
                    kept = {
                        "hash": digest,
                        "text": text,
                        "read_on": today.isoformat(),
                        "found": found,
                        "closures": kept.get("closures"),
                    }
                    redraw = True
        if redraw and kept.get("hash") == digest:
            wanted, kept["unplaced"], lost = drawn(
                source, kept.get("found") or [], get_json, kept.get("closures")
            )
            kept["closures"] = wanted
            unread += lost
        pages[source.key] = kept
        missed += int(kept.get("unplaced") or 0)
        # What was last drawn from this page, also while it waits to be asked again.
        for name, count in apply(source, kept.get("closures") or [], today).items():
            totals[name] += count
    state.update(pages=pages, calls={"day": today.isoformat(), "n": used})
    _save(state)
    parts = [
        f"read {read_ok} of {len(SOURCES)} pages, screened {screened}, asked {asked}",
        f"entered {totals['entered']}, extended {totals['extended']}, ended {totals['ended']}",
        f"not placed {missed}",
    ]
    if unread:
        parts.append(f"map not read for {unread}")
    if totals["refused"]:
        parts.append(f"refused {totals['refused']}")
    if failed:
        parts.append("failed " + ", ".join(failed))
    if cut:
        parts.append("cut " + ", ".join(cut))
    if capped:
        parts.append(f"over the day's {CALLS_PER_DAY} asks: " + ", ".join(capped))
    return "; ".join(parts)


__all__ = ["KEY", "SOURCES", "alert_key", "apply", "ask", "page_text", "place", "read", "run"]
