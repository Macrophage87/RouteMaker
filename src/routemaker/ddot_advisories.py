"""Closures from DDOT's project traffic advisories (v0.12.4).

The owner, 2026-10-25, of the Connecticut Avenue Streetscape and Deckover project's advisories
page: "maybe use these advisories for DC. They tend to have fairly up to date closures. ...
somehow the conneticut avenue deckover was missed." DDOT's big projects each have an ArcGIS Hub
site whose "Traffic Advisories" (or "Construction Updates") page lists press releases, newest
first, each a dated title and a PDF or Word file. There is no feed: the page is text, and the
release says in words which block closes, from when, for how long.

So the closures are read by a person and kept here, in `src/core/geodata/ddot-advisories.json`:
each one the advisory's dates, the OpenStreetMap ways it closes and their lines, a reason and
the links. They are real closures (source "ddot_advisory"), routed round like an MPD advisory's
or a reviewer's, and unlike a TOPS permit, which only says a road may close
(`workzones.POSSIBLE_SOURCES`). A window is whole days in the region's time, from the start of
the first day to the midnight after the last, as a reviewer's; "for approximately eight weeks"
is read to its end, and a closure "for the duration of the project" to the project's own
expected end. One past its last day drops out by itself.

New advisories are found by `scripts/ddot_advisories.py watch`, which lists the dated entries
of every DDOT project's advisories page that are not yet in the file's `seen` list
(`page_entries` parses a page). docs/OPERATIONS.md, "DDOT project advisories", has the steps.

Pure: no network, no database. `core.workzones.snapshot` adds `zones(now)` to the snapshot.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from . import workzones as wz
from .ridetime import ZONE

SOURCE = "ddot_advisory"
GEODATA = Path(__file__).resolve().parents[1] / "core" / "geodata" / "ddot-advisories.json"


@dataclass(frozen=True)
class Closure:
    closure_id: str
    project: str
    page: str
    advisory: str
    posted: date
    road: str
    reason: str
    first_day: date
    last_day: date
    lines: tuple[tuple[tuple[float, float], ...], ...]
    # The last day is a guess ("for the duration of the project" read to the project's
    # expected end): `reminders` asks for it to be checked before it comes.
    end_estimated: bool = False

    @property
    def start(self) -> datetime:
        return datetime.combine(self.first_day, time(0), ZONE)

    @property
    def end(self) -> datetime:
        """The midnight after the last day (`workzones.last_day` says it as "through")."""
        return datetime.combine(self.last_day + timedelta(days=1), time(0), ZONE)


def parse(data: Mapping) -> tuple[list[Closure], str]:
    """The file's closures, and the day it was last changed."""
    out = []
    for row in data.get("closures") or []:
        lines = tuple(
            tuple((float(p[0]), float(p[1])) for p in line)
            for line in row.get("lines") or []
            if isinstance(line, list) and len(line) >= 2
        )
        out.append(
            Closure(
                closure_id=str(row["id"]),
                project=str(row["project"]),
                page=str(row["page"]),
                advisory=str(row.get("advisory") or row["page"]),
                posted=date.fromisoformat(row["posted"]),
                road=str(row["road"]),
                reason=str(row["reason"]),
                first_day=date.fromisoformat(row["first_day"]),
                last_day=date.fromisoformat(row["last_day"]),
                lines=lines,
                end_estimated=bool(row.get("end_estimated")),
            )
        )
    return out, str(data.get("updated") or "")


@lru_cache(maxsize=1)
def _loaded() -> tuple[tuple[Closure, ...], str]:
    closures, updated = parse(json.loads(GEODATA.read_text()))
    return tuple(closures), updated


def updated() -> str:
    """The day the file last changed: the source's "read at", so the route cache's key stays
    the same until it does."""
    return _loaded()[1]


# A hand-read file not changed in this many days is labelled stale (its closures still stand,
# their heads-ups say they may be out of date); a guessed last day this near is a reminder to
# check it (audit 2026-10-29: a closure on a guessed end dropped out silently, and the file
# never looked old, however long since it was read).
STALE_DAYS = 45
WARN_DAYS = 30


def stale(updated: str, today: date) -> bool:
    """Whether a hand-read file last changed on `updated` (ISO) is past `STALE_DAYS`."""
    try:
        return (today - date.fromisoformat(updated)).days > STALE_DAYS
    except ValueError:
        return True


def reminders(name: str, closures, updated: str, today: date) -> list[str]:
    """What to check in a hand-read file (`scripts/ddot_advisories.py watch` prints them): a
    guessed last day within `WARN_DAYS`, and the file not changed in `STALE_DAYS`."""
    out = [
        f"{name}: {c.road} ends {c.last_day.isoformat()} by estimate; check it is still right"
        for c in closures
        if c.end_estimated and today <= c.last_day <= today + timedelta(days=WARN_DAYS)
    ]
    if stale(updated, today):
        out.append(f"{name}: not updated since {updated or 'never'}; read the source again")
    return out


def check_due(today: date) -> list[str]:
    """This file's `reminders`."""
    closures, updated = _loaded()
    return reminders("DDOT advisories", closures, updated, today)


def zones_of(closure: Closure, source: str = SOURCE) -> list[wz.Zone]:
    """A closure's zones, one a line. `source` is another hand-read file's own
    (`routemaker.purple_line`), which keeps this file's shape."""
    published = datetime.combine(closure.posted, time(0), ZONE)
    return [
        wz.Zone(
            zone_id=f"{source}-{closure.closure_id}-{index}",
            source=source,
            kind=wz.CLOSED,
            penalty_s=0.0,
            line=line,
            road=closure.road,
            description=closure.reason,
            start=closure.start,
            end=closure.end,
            reason=closure.reason,
            title=f"{closure.road}: closed",
            url=closure.page,
            published=published,
        )
        for index, line in enumerate(closure.lines)
    ]


def zones(now: datetime, closures=None) -> list[wz.Zone]:
    """The closures not yet past their last day: in force now or later."""
    found = _loaded()[0] if closures is None else closures
    return [zone for c in found if c.end > now for zone in zones_of(c)]


# --- Finding new advisories (scripts/ddot_advisories.py watch) --------------------------------

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}}),\s*(20\d\d)\b")
# A weekly report's "5/12/2025 - 5/18/2025": its first day.
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
# A collapsible section's own words ("Accordion", "April 2025", the table's headings).
_FURNITURE = re.compile(
    rf"^.*?\bDescription\s+Date(\s+Download Document)?\s+|^\s*Accordion\s+({_MONTHS})?\s*(20\d\d)?"
)
# A link's own words, not the advisory's title.
_BUTTONS = re.compile(r"\b(Download Advisory|Download Document|View|Download)\b", re.I)


@dataclass(frozen=True)
class Entry:
    """One dated advisory on a project's page."""

    day: date | None
    title: str
    link: str


class _Tokens(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._href = href if href.startswith("http") else None

    def handle_endtag(self, tag):
        # A link closes its entry: its own words ("Download Advisory", or a banner's whole
        # title) are part of it.
        if tag == "a" and self._href:
            self.items.append(("link", self._href))
            self._href = None

    def handle_data(self, data):
        self.items.append(("text", data))


def _markdown(node) -> list[str]:
    """Every card's HTML on a Hub page, in page order."""
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "markdown" and isinstance(value, str):
                out.append(value)
            else:
                out.extend(_markdown(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(_markdown(value))
    return out


def page_entries(page: Mapping) -> list[Entry]:
    """The advisories a Hub page lists: each document link, with the words since the link
    before it (its own included) as its title and the first date among them as its day. Both
    of DDOT's layouts read this way: a dated heading, a title and a button; or a table row of
    title, date and button. So does a site's banner, its title the link's own words."""
    out: list[Entry] = []
    for html in _markdown(page):
        html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
        parser = _Tokens()
        parser.feed(html)
        words: list[str] = []
        for kind, value in parser.items:
            if kind == "text":
                words.append(value)
                continue
            text = _BUTTONS.sub(" ", " ".join(words))
            text = " ".join(text.split())
            if text.startswith("Advisories"):
                text = text[len("Advisories") :].strip()
            words = []
            text = _FURNITURE.sub("", text).strip()
            found = _DATE.search(text)
            day = None
            title = text
            numeric = None if found else _NUMERIC.search(text)
            if numeric:
                try:
                    day = date(int(numeric.group(3)), int(numeric.group(1)), int(numeric.group(2)))
                except ValueError:
                    day = None
            if found:
                month = _MONTHS.split("|").index(found.group(1)) + 1
                try:
                    day = date(int(found.group(3)), month, int(found.group(2)))
                except ValueError:
                    day = None
                # A dated heading before its title; a table row's date (or a date in the
                # title's own words) is left where it is.
                if found.start() == 0:
                    title = text[found.end() :]
            title = title.strip(" .,-")
            if not title and day is None:
                continue
            out.append(Entry(day, title, value))
    return out


# An undated entry still counts when its words say it closes something (a site's home page
# shows its newest advisory as a banner with no date: the Theodore Roosevelt Bridge's).
_CLOSING = re.compile(r"\b(clos(e|ed|es|ing|ure|ures)|detour|advisory)\b", re.I)


def unseen(entries: list[Entry], seen: set[str], since: date | None = None) -> list[Entry]:
    """The entries not yet read (by link), dated on or after `since` where one is given. An
    undated one then counts only when its words name a closure, a detour or an advisory: the
    page's own change date brought it in, not its own."""
    return [
        e
        for e in entries
        if e.link not in seen
        and (
            since is None
            or (e.day is not None and e.day >= since)
            or (e.day is None and _CLOSING.search(e.title) is not None)
        )
    ]
