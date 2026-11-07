"""Closures from the Fairfax County Park Authority's Park Alerts page (v0.22.0).

A closure on the Cross County Trail at Lake Accotink was missed (the owner: "There's a closure on
the cross county trail. See where this is posted and how it was missed."). It was posted only on
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
    r"\b(\w*trails?|\w*bridges?|boardwalks?|walkways?|paths?|greenway|stream valley|underpass"
    r"|crossings?|fords?|cross county|cct|detour|culverts?)\b",
    re.I,
)

# What holds one park's notice: a top-level list item, or a paragraph outside any list.
_BLOCKS = ("li", "p")
_BOLD = ("strong", "b")


class _Items(HTMLParser):
    """The alert's top-level items: each list item (a nested list stays in its item) and each
    paragraph outside a list, with the bold words that open it (the park's name)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0  # list items open
        self.outer: str | None = None  # the open item's tag
        self.items: list[tuple[str, str]] = []
        self._text: list[str] = []
        self._bold: list[str] = []
        self._in_bold = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "li":
            self.depth += 1
        if self.outer is None and tag in _BLOCKS:
            self.outer, self._text, self._bold = tag, [], []
        elif tag in _BOLD and self.outer and not self._bold and not "".join(self._text).strip():
            self._in_bold = True
        elif tag in ("br", "p", "li") and self.outer:
            self._text.append(" ")

    def handle_endtag(self, tag) -> None:
        if tag == "li" and self.depth:
            self.depth -= 1
        if tag in _BOLD:
            self._in_bold = False
        if self.outer == tag and (tag != "li" or self.depth == 0):
            self.items.append(("".join(self._bold), "".join(self._text)))
            self.outer = None
        elif self.outer:
            self._text.append(" ")

    def handle_data(self, data) -> None:
        if self.outer:
            self._text.append(data)
            if self._in_bold:
                self._bold.append(data)


def _single(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def alert_items(page: str) -> list[Item]:
    """The Park Alerts page's items, in its order: each park's notice. Only the alerts' own
    bodies are read (the page's menus are lists too), every one on the page."""
    out = []
    start = page.find("field--name-body")
    while start >= 0:
        end = page.find("</article>", start)
        body = page[start : end if end > 0 else len(page)]
        parser = _Items()
        parser.feed(body[body.find(">") + 1 :])
        for bold, words in parser.items:
            text = _single(words)
            if not text:
                continue
            park = _single(bold).rstrip(":").strip()
            out.append(Item(park, text, hashlib.sha1(text.encode()).hexdigest()[:12]))
        start = page.find("field--name-body", start + 1)
    return out


def unseen(items: list[Item], seen: set[str]) -> list[Item]:
    """The items not yet read, trail ones first, each kind in the page's order."""
    fresh = [i for i in items if i.key not in seen]
    return [i for i in fresh if i.trail] + [i for i in fresh if not i.trail]
