"""Closures from the Fairfax County Park Authority's Park Alerts page (v0.22.0).

The owner, 2026-11-07, stopped at Lake Accotink on the Cross County Trail: "There's a closure on
the cross county trail. See where this is posted and how it was missed." It was posted only on
the Park Authority's "Park Alerts: Park Status Notices" page
(https://www.fairfaxcounty.gov/parks/park-alerts): "Lake Accotink Park: The bridge near the
marina is temporarily closed for repairs ... reopen by Friday, Nov. 13." No feed covers Fairfax
County's park trails: Virginia's WZDx feed is VDOT's roads, and the park pages say nothing.

The page is one list item a park, in words, with no map. So, as for the Purple Line
(`routemaker.purple_line`), a person reads it into `src/core/geodata/fcpa-closures.json`, in the
shape of DDOT's project advisories (`routemaker.ddot_advisories`, whose `parse` and `zones_of`
this uses): real closures (source "fcpa"), routed round, whole days, gone after their last day.
The owner chose (2026-11-07) "Watch Park Alerts, you confirm": `scripts/fcpa_alerts.py watch`
lists the page's items not yet read (`alert_items`, `unseen`), trail ones first, and a closure
goes in only after the owner confirms it. docs/OPERATIONS.md, "Fairfax park trail closures",
has the steps.

Pure: no network, no database. `core.workzones.snapshot` adds `zones(now)` to the snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from . import ddot_advisories
from . import workzones as wz

SOURCE = "fcpa"
GEODATA = Path(__file__).resolve().parents[1] / "core" / "geodata" / "fcpa-closures.json"
PAGE = "https://www.fairfaxcounty.gov/parks/park-alerts"


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
    """What to check in the file (`ddot_advisories.reminders`): a guessed last day close by,
    or the file not read for a while."""
    closures, read = _loaded()
    return ddot_advisories.reminders("Fairfax Park Alerts", closures, read, today)


# --- Finding new alerts (scripts/fcpa_alerts.py watch) ----------------------------------------


@dataclass(frozen=True)
class Item:
    park: str  # "Lake Accotink Park"; "" where the item names none
    text: str  # the item's words, white space made single
    key: str  # what `seen` keeps: a hash of the words, so an edited item is read again

    @property
    def trail(self) -> bool:
        """Whether it may close a way a bicycle uses: a trail, a bridge, a path."""
        return _TRAIL.search(self.text) is not None


_TRAIL = re.compile(
    r"\b(trails?|bridges?|boardwalks?|paths?|greenway|stream valley|cross county|detour"
    r"|culverts?)\b",
    re.I,
)


class _Items(HTMLParser):
    """The alert's top-level list items (a nested list stays in its item)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.items: list[tuple[str, str]] = []
        self._text: list[str] = []
        self._strong: list[str] = []
        self._in_strong = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "li":
            if self.depth == 0:
                self._text, self._strong = [], []
            self.depth += 1
        elif tag == "strong" and self.depth == 1 and not self._strong:
            self._in_strong = True
        elif tag in ("br", "p") and self.depth:
            self._text.append(" ")

    def handle_endtag(self, tag) -> None:
        if tag == "li" and self.depth:
            self.depth -= 1
            self._text.append(" ")
            if self.depth == 0:
                self.items.append(("".join(self._strong), "".join(self._text)))
        elif tag == "strong":
            self._in_strong = False

    def handle_data(self, data) -> None:
        if self.depth:
            self._text.append(data)
            if self._in_strong:
                self._strong.append(data)


def _single(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def alert_items(page: str) -> list[Item]:
    """The Park Alerts page's items, in its order: each park's notice. Only the alert's own
    body is read (the page's menus are lists too)."""
    start = page.find("field--name-body")
    if start < 0:
        return []
    end = page.find("</article>", start)
    body = page[start : end if end > 0 else len(page)]
    body = body[body.find(">") + 1 :]
    parser = _Items()
    parser.feed(body)
    out = []
    for strong, words in parser.items:
        text = _single(words)
        if not text:
            continue
        park = _single(strong).rstrip(":").strip()
        out.append(Item(park, text, hashlib.sha1(text.encode()).hexdigest()[:12]))
    return out


def unseen(items: list[Item], seen: set[str]) -> list[Item]:
    """The items not yet read, trail ones first, each kind in the page's order."""
    fresh = [i for i in items if i.key not in seen]
    return [i for i in fresh if i.trail] + [i for i in fresh if not i.trail]
