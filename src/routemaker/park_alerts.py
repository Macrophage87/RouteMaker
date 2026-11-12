"""Trail closures from the park agencies that run the trails (v0.26.0).

Backlog 2026-11-12, item 8, which the owner approved ("Let's get the top 12"): the owner's own
reported misses were trail closures (the Cross County Trail at Lake Accotink, the Met Branch
Trail), and a trail closure usually has no way round nearby, so it is learnt at the barrier. The
agencies post them only as words on their own pages, with no feed and no map:

- **NOVA Parks** (the W&OD Trail): one page an alert, each linked from the site's home page
  (`nova_links`, `nova_item`), e.g. "W&OD - November 17-24. Trail Detours Will be in Place for
  Construction in Falls Church at Grove Ave, N. West St, Park Ave."
- **NPS, C&O Canal**: the "Towpath and Park Conditions" page lists each place by its milepost
  ("Little Falls (MP 4.7)") and its state ("Open", "Closed", "Work Alert", "Detour")
  (`choh_items`). A closure that names mileposts is drawn along the towpath between them from
  the mile lines the app already has (`towpath_lines`, from `trail-miles.json`), not as a
  park-wide notice (the NPS alerts feed, `dc_closures.parse_nps`, stays park-level).
- **Anne Arundel County Recreation and Parks** (the B&A Trail, the WB&A's county end): its
  "Closings, Cancellations, & Delays" list (`aacounty_items`).

Montgomery Parks, Arlington County and Prince George's parks are not read yet: none was found to
post trail closures on one public page a script can read (2026-11-12: Montgomery Parks posts
them as news items, Arlington's pages refuse scripts, Prince George's alerts page is filled by
script from Nixle). docs/OPERATIONS.md, "Park agency trail closures", has what was checked.

As for Fairfax's park alerts (`routemaker.fcpa`), a person reads each new item and a closure goes
in `src/core/geodata/park-closures.json` (the DDOT advisories' shape, `ddot_advisories.parse`;
each closure's `project` names its agency) only as the owner's rule for these says:
`scripts/park_alerts.py watch` lists the items not yet in the file's `seen` list, an agency at a
time, trail ones first. They are real closures (source "park_alert"), routed round, whole days,
gone after their last day.

Pure: no network, no database. `core.workzones.snapshot` adds `zones(now)` to the snapshot.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin

from . import ddot_advisories
from . import workzones as wz

SOURCE = "park_alert"
GEODATA = Path(__file__).resolve().parents[1] / "core" / "geodata" / "park-closures.json"
TRAIL_MILES = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "amenity-data" / "trail-miles.json"
)
MILE_M = 1609.344


@dataclass(frozen=True)
class Agency:
    key: str
    name: str
    page: str


NOVA = Agency("nova", "NOVA Parks", "https://www.novaparks.com/")
CHOH = Agency("choh", "NPS, C&O Canal", "https://www.nps.gov/choh/planyourvisit/conditions.htm")
AACOUNTY = Agency(
    "aacounty",
    "Anne Arundel County Recreation and Parks",
    "https://www.aacounty.org/recreation-parks/about-us/closings-cancellations",
)
AGENCIES = {a.key: a for a in (NOVA, CHOH, AACOUNTY)}


@lru_cache(maxsize=1)
def _loaded() -> tuple[tuple[ddot_advisories.Closure, ...], str]:
    closures, updated = ddot_advisories.parse(json.loads(GEODATA.read_text()))
    return tuple(closures), updated


def updated() -> str:
    """The day the file last changed: the source's "read at"."""
    return _loaded()[1]


def zones(now: datetime, closures=None) -> list[wz.Zone]:
    """The closures not yet past their last day: in force now or later."""
    found = _loaded()[0] if closures is None else closures
    return [z for c in found if c.end > now for z in ddot_advisories.zones_of(c, SOURCE)]


def check_due(today: date) -> list[str]:
    """What to check in the file: a guessed last day close by, or the file not read for a while
    (`ddot_advisories.reminders`)."""
    closures, read = _loaded()
    return ddot_advisories.reminders("Park agency trail alerts", closures, read, today)


# --- Finding new alerts (scripts/park_alerts.py watch) ----------------------------------------


@dataclass(frozen=True)
class Item:
    agency: str  # `Agency.key`
    place: str  # "W&OD", "Little Falls (MP 4.7)", "B&A Trail Closure"
    text: str  # the item's words, white space made single
    link: str  # the item's own page, else the agency's
    key: str  # what `seen` keeps: a hash of the words, so an edited item is read again
    miles: tuple[float, float] | None = None  # C&O: the mileposts it names

    @property
    def trail(self) -> bool:
        """Whether it may close a way a bicycle uses: a trail, a towpath, a bridge, a path."""
        return _TRAIL.search(f"{self.place} {self.text}") is not None


_TRAIL = re.compile(
    r"\b(\w*trails?|towpath|w&od|b&a|wb&a|\w*bridges?|aqueducts?|boardwalks?|paths?|greenway"
    r"|underpass|tunnel|detour(?:ed|s)?|culverts?|crossings?)\b",
    re.I,
)


def _text(fragment: str) -> str:
    """An HTML fragment's words, tags dropped and white space made single."""
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    words = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", words).strip()


def _item(agency: str, place: str, text: str, link: str, miles=None) -> Item:
    key = hashlib.sha1(f"{place}\n{text}".encode()).hexdigest()[:12]
    return Item(agency, place, text, link, key, miles)


# NOVA Parks: the home page links each alert ("/alert/<slug>").
_NOVA_LINK = re.compile(r'href="(/alert/[^"#?]+)"')


def nova_links(home: str) -> list[str]:
    """The alerts' pages the home page links, in its order, each once."""
    out: list[str] = []
    for path in _NOVA_LINK.findall(home):
        url = urljoin(NOVA.page, path)
        if url not in out:
            out.append(url)
    return out


_NOVA_TITLE = re.compile(r'<h2 class="page-title">(.*?)</h2>', re.S | re.I)
_NOVA_BODY = re.compile(r"field--name-body[^>]*>(.*?)</article>", re.S | re.I)


def nova_item(url: str, page: str) -> Item | None:
    """An alert's page: its title (the trail and the days, "W&OD -November 17-24. Trail Detours
    ...") and its body's words (the page's own `<h1>` is only "Park Alerts")."""
    title = _NOVA_TITLE.search(page)
    if title is None or not _text(title.group(1)):
        return None
    body = _NOVA_BODY.search(page, title.end())
    return _item(NOVA.key, _text(title.group(1)), _text(body.group(1)) if body else "", url)


# NPS, C&O Canal: "<h4>Little Falls (MP 4.7)</h4> <ul><li><span>Work Alert</span>, ...</li>".
_CHOH_PLACE = re.compile(r"<h4>(.*?)</h4>", re.S | re.I)
# A state's line: a list item that opens with a coloured state ("<li><span ...>Closed</span>, ...").
_CHOH_STATE = re.compile(r"<li>\s*<span\b", re.I)
_NUMBER = r"(\d+(?:\.\d+)?)"
_MILES = re.compile(rf"\bMP\s*{_NUMBER}", re.I)
# A stretch in the words: "Miles 106 - 106.8", "between milepost 84.4 and milepost 89.1".
_STRETCH = re.compile(
    rf"\b(?:miles?|mileposts?|MP)\s*{_NUMBER}\s*(?:-|–|to|and)\s*(?:miles?|mileposts?|MP)?\s*"
    rf"{_NUMBER}",
    re.I,
)
OPEN = re.compile(r"^\s*open\b", re.I)


def choh_items(page: str) -> list[Item]:
    """The conditions page's states that are not plain "Open", one item each, with the place's
    mileposts: a closed parking lot is listed too (the trail ones come first in the watch)."""
    out = []
    places = list(_CHOH_PLACE.finditer(page))
    for n, match in enumerate(places):
        place = _text(match.group(1))
        end = places[n + 1].start() if n + 1 < len(places) else len(page)
        block = page[match.end() : end]
        cut = re.search(r"<h[1-3]\b", block, re.I)
        block = block[: cut.start()] if cut else block
        found = _MILES.search(place)
        states = [m.start() for m in _CHOH_STATE.finditer(block)]
        for k, start in enumerate(states):
            line = _text(block[start : states[k + 1] if k + 1 < len(states) else len(block)])
            label, _comma, words = line.partition(",")
            label, words = label.strip(), words.strip(" ,")
            if not label or OPEN.match(label):
                continue
            stretch = _STRETCH.search(line)
            if stretch:
                miles = (float(stretch.group(1)), float(stretch.group(2)))
            elif found:
                miles = (float(found.group(1)),) * 2
            else:
                miles = None
            out.append(_item(CHOH.key, place, f"{label}: {words}", CHOH.page, miles))
    return out


# Anne Arundel: "<div class="zn-alert-list-entry ..."> badge, "<h3 class="zn-title">", body.
_AA_ENTRY = re.compile(r'<div class="zn-alert-list-entry\b', re.I)
_AA_BADGE = re.compile(r'<span class="badge[^"]*">(.*?)<', re.S | re.I)
_AA_TITLE = re.compile(r'<h3 class="zn-title">(.*?)</h3>', re.S | re.I)
_AA_BODY = re.compile(r'<div class="zn-body">(.*?)</div>', re.S | re.I)


def aacounty_items(page: str) -> list[Item]:
    """The closings list's entries: badge ("Closed"), title and words."""
    out = []
    starts = [m.start() for m in _AA_ENTRY.finditer(page)]
    for n, start in enumerate(starts):
        entry = page[start : starts[n + 1] if n + 1 < len(starts) else len(page)]
        title = _AA_TITLE.search(entry)
        if title is None:
            continue
        badge = _AA_BADGE.search(entry)
        body = _AA_BODY.search(entry)
        label = _text(badge.group(1)) if badge else ""
        words = _text(body.group(1)) if body else ""
        text = f"{label}: {words}" if label else words
        out.append(_item(AACOUNTY.key, _text(title.group(1)), text, AACOUNTY.page))
    return out


def unseen(items: list[Item], seen: set[str]) -> list[Item]:
    """The items not yet read, trail ones first, each kind in the page's order."""
    fresh = [i for i in items if i.key not in seen]
    return [i for i in fresh if i.trail] + [i for i in fresh if not i.trail]


# --- The C&O by milepost (scripts/park_alerts.py towpath) -------------------------------------


def _metres(a, b) -> float:
    """Metres between two (lon, lat) points (haversine)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def _between(a, b, share: float) -> tuple[float, float]:
    return (round(a[0] + (b[0] - a[0]) * share, 5), round(a[1] + (b[1] - a[1]) * share, 5))


def towpath_lines(first_mile: float, last_mile: float, data: dict | None = None) -> list[list]:
    """The C&O towpath's lines from one milepost to another, cut from the trail mile lines
    (`trail-miles.json`: OpenStreetMap's ways, simplified to about 10 m, each piece with `s`, its
    first point's distance from mile 0 in metres, set from the posted mile markers), ready for a
    closure's `lines`. A stretch the mile lines do not cover has no line, and the caller says so:
    on 2026-11-12 they had gaps at about miles 9.0-19.6, 22.09-22.12, 54.1-54.75 and 93.15-93.36,
    and stopped at mile 106.05."""
    if data is None:
        data = json.loads(TRAIL_MILES.read_text())
    low, high = sorted((first_mile * MILE_M, last_mile * MILE_M))
    if high - low < 1.0:
        low, high = low - 50.0, high + 50.0  # one milepost: 50 m either side (our default)
    out = []
    for trail in data.get("trails") or []:
        if "chesapeake and ohio canal" not in str(trail.get("n", "")).lower():
            continue
        along = float(trail.get("s") or 0.0)
        points = [tuple(p) for p in trail.get("l") or []]
        cut: list[tuple[float, float]] = []
        for a, b in zip(points, points[1:], strict=False):
            length = _metres(a, b)
            start, end = along, along + length
            if end > low and start < high and length > 0:
                if not cut:
                    cut.append(_between(a, b, max(0.0, (low - start) / length)))
                point = _between(a, b, min(1.0, (high - start) / length))
                if point != cut[-1]:
                    cut.append(point)
            along = end
        if len(cut) >= 2:
            out.append([list(p) for p in cut])
    out.sort(key=lambda line: -line[0][0])  # from Georgetown westward
    return out


__all__ = [
    "AGENCIES",
    "SOURCE",
    "Item",
    "aacounty_items",
    "check_due",
    "choh_items",
    "nova_item",
    "nova_links",
    "towpath_lines",
    "unseen",
    "updated",
    "zones",
]
