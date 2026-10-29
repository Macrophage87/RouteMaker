"""The 311 log (Stephen, 2026-10-20: "texting for 311 doesn't work. Perhaps instead we enable it
everywhere as a log with what website to go to and the description of where. Such as marking
potholes along a route.").

DC's Text to 311 (32311) answers every message, even a plain NEW, with only "Welcome to DC311"
(Stephen's screenshot, 2026-10-20), so the text message it was sent as no longer reports
anything. A problem is now logged instead: from a ride's 311 button, or from the road panel's
"Log for 311" (a right-click or a long press on the map). Each entry keeps what it is, where (the
road's name and the GPS position), the day, an optional note, and whether the rider has reported it.
The log's list says which 311 website takes it (frontend lib/report311Log.ts holds the sites),
copies the report and opens the site.

The day, never the time of day (Stephen, 2026-10-29: the log keeps the date, not the time of day;
the exact spot stays, because crews need it to find the pothole): an entry's `at` (logged),
`changed` and `reported` are days in Washington's time ("2026-10-20"), and its id is random, with
no time in it. `dated` cuts what an older page sends (full times, and ids that began with the time
they were made) to that, and migration 0052 did the same to the logs already kept. Two changes to
one entry on the same day are told apart by its `rev`, a count of its changes.

Two pieces live here:

- `log_problem`: the shape and size checks for the log document a signed-in rider keeps with the
  account (core.models.Report311Log, GET and POST /api/me/report311-log), and `merge_logs`, which
  folds a device's copy into the account's by entry, so a device with an old copy cannot drop
  entries another device logged. Signed out, the log stays on the device.
- `where`: which jurisdiction's 311 takes a point (POST /api/report311/where, the point in the
  body, never the URL): DC from its own boundary (core/geodata/dc-boundary.geojson, the one the
  map draws), elsewhere the county or independent city from the self-hosted Photon's answer for
  the point (OpenStreetMap's administrative boundaries). The point is not kept, and the answer is
  only an id.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime, time
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from . import geocode

ENTRIES_MAX = 300
ID_MAX = 40
PLACE_MAX = 200
NOTE_MAX = 500
LOG_MAX_BYTES = 160 * 1024
# The most changes one entry counts (`rev`).
REV_MAX = 1_000_000
# The log's days are Washington's (frontend lib/report311Log.ts dayOf).
DAY_ZONE = ZoneInfo("America/New_York")

# What an entry keeps (lib/report311Log.ts LogEntry).
FIELDS = frozenset(
    ("id", "kind", "lat", "lon", "place", "note", "at", "changed", "rev", "where", "reported")
)

KINDS = ("pothole", "tree", "bikeLane", "obstruction", "streetlight", "other")

DC_BOUNDARY = Path(__file__).resolve().parent / "geodata" / "dc-boundary.geojson"

# The jurisdictions whose 311 sites the log names (frontend lib/report311Log.ts JURISDICTIONS has
# the same ids, with each site's address and source). Maryland's counties and Baltimore City take
# reports for their own roads; Virginia's counties other than Arlington have their roads kept by
# VDOT, so those are VDOT's ("va"), and Virginia's cities keep their own.
COUNTIES = {
    "MD": {
        "montgomery": "moco",
        "prince george's": "pg",
        "baltimore": "baltimore-county",
        "howard": "howard",
        "anne arundel": "anne-arundel",
        "frederick": "frederick",
        "carroll": "carroll",
        "harford": "harford",
        "charles": "charles",
    },
    "VA": {
        "arlington": "arlington",
        "fairfax": "va",
        "loudoun": "va",
        "prince william": "va",
    },
}
# Independent cities (county-equivalents): Photon names them as the county ("Alexandria",
# "City of Alexandria") or, where it has no county, as the city.
CITIES = {
    "MD": {"baltimore": "baltimore-city"},
    "VA": {
        "alexandria": "alexandria",
        "fairfax": "fairfax-city",
        "falls church": "falls-church",
        "manassas": "manassas",
        "manassas park": "manassas-park",
    },
}
# Elsewhere in a state: its own road department's page (a numbered state road, or a county not
# listed above).
STATE_FALLBACK = {"MD": "md", "VA": "va"}
STATE_NAMES = {"district of columbia": "DC", "maryland": "MD", "virginia": "VA"}
# "none": looked up, and in no jurisdiction the log names (the page then says so).
JURISDICTION_IDS = frozenset(
    {"dc", "none", *STATE_FALLBACK.values()}
    | {j for state in COUNTIES.values() for j in state.values()}
    | {j for state in CITIES.values() for j in state.values()}
)

_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A day as the API serves it (`served`): noon in Washington, with its offset.
_SERVED_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})T12:00:00[+-]\d{2}:\d{2}$")
# An id as the page made them before 2026-10-29: the time it was made (milliseconds, base 36),
# then a random part. Cut to the random part (lib/report311Log.ts the same).
_TIMED_ID = re.compile(r"^[0-9a-z]{8}-([0-9a-z]{1,8})$")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _time(value) -> bool:
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _entry_problem(entry) -> str | None:
    if not isinstance(entry, dict):
        return "Each entry must be an object."
    if set(entry) - FIELDS:
        return "An entry has a field this log does not keep."
    if not isinstance(entry.get("id"), str) or not _ID.match(entry["id"]):
        return "An entry's id is not in the expected form."
    if entry.get("kind") not in KINDS:
        return f"An entry's kind is one of {', '.join(KINDS)}."
    lat, lon = entry.get("lat"), entry.get("lon")
    if not (_finite(lat) and _finite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return "An entry's position is not a latitude and longitude."
    place = entry.get("place")
    if place is not None and (not isinstance(place, str) or len(place) > PLACE_MAX):
        return f"An entry's place is text of at most {PLACE_MAX} characters."
    note = entry.get("note", "")
    if not isinstance(note, str) or len(note) > NOTE_MAX:
        return f"An entry's note is text of at most {NOTE_MAX} characters."
    if not _time(entry.get("at")):
        return "An entry's time is not in the expected form."
    changed = entry.get("changed")
    if changed is not None and not _time(changed):
        return "An entry's changed time is not in the expected form."
    rev = entry.get("rev", 0)
    if not isinstance(rev, int) or isinstance(rev, bool) or not 0 <= rev <= REV_MAX:
        return "An entry's count of changes is not a whole number in range."
    where = entry.get("where")
    if where is not None and where not in JURISDICTION_IDS:
        return "An entry's 311 site is not one this log knows."
    reported = entry.get("reported")
    if reported is not None and not _time(reported):
        return "An entry's reported time is not in the expected form."
    return None


def log_problem(entries) -> str | None:
    """Why a log document cannot be kept, or None."""
    if not isinstance(entries, list):
        return "The log must be a list."
    if len(entries) > ENTRIES_MAX:
        return f"The log keeps at most {ENTRIES_MAX} entries."
    seen = set()
    for entry in entries:
        problem = _entry_problem(entry)
        if problem:
            return problem
        if entry["id"] in seen:
            return "Two entries have the same id."
        seen.add(entry["id"])
    if log_bytes(entries) > LOG_MAX_BYTES:
        return f"The log is larger than {LOG_MAX_BYTES // 1024} KB."
    return None


def log_bytes(entries: list) -> int:
    """The log's size as UTF-8 JSON, as the page measures it (lib/report311Log.ts capLog)."""
    return len(json.dumps(entries, separators=(",", ":"), ensure_ascii=False).encode())


def _when(value: str) -> datetime:
    found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return found if found.tzinfo is not None else found.replace(tzinfo=UTC)


def today(now: datetime | None = None) -> date:
    """Today in Washington, the log's day."""
    return (now or datetime.now(UTC)).astimezone(DAY_ZONE).date()


def day_of(value: str) -> str:
    """The day of an entry's time, in Washington ("2026-10-20"); a day stays as it is."""
    if _DAY.match(value):
        return value
    served_day = _SERVED_DAY.match(value)
    if served_day:
        return served_day.group(1)
    return _when(value).astimezone(DAY_ZONE).date().isoformat()


def _noon(day: str) -> str:
    return datetime.combine(date.fromisoformat(day), time(12), tzinfo=DAY_ZONE).isoformat()


def served(entries: list[dict]) -> list[dict]:
    """The log as the API answers it: `dated`, then each day as noon in Washington with its offset
    ("2026-10-20T12:00:00-04:00"). A page of the release before reads a bare day as midnight UTC,
    which it shows as the evening before; it shows noon as the right day (at "12:00 PM", the same
    for every entry, so it says nothing of when). The page of this release reads only the day.
    Kept as days; only the answer carries noon."""
    out = []
    for entry in entries:
        entry = dated(entry)
        for key in ("at", "changed", "reported"):
            if isinstance(entry.get(key), str) and _DAY.match(entry[key]):
                entry[key] = _noon(entry[key])
        out.append(entry)
    return out


def dated(entry: dict) -> dict:
    """An entry as the log keeps it: its times cut to their days, and an id that began with the
    time it was made cut to its random part."""
    out = dict(entry)
    for key in ("at", "changed", "reported"):
        if isinstance(out.get(key), str):
            out[key] = day_of(out[key])
    timed = _TIMED_ID.match(out["id"])
    if timed:
        out["id"] = timed.group(1)
    return out


def _changed(entry: dict) -> tuple[datetime, int]:
    # The day it last changed, then, within a day, how many changes it has had.
    return _when(entry.get("changed") or entry["at"]), entry.get("rev") or 0


def cap_log(entries: list[dict]) -> list[dict]:
    """At most ENTRIES_MAX and LOG_MAX_BYTES: the oldest archived go first, then the oldest open
    (lib/report311Log.ts capLog, the same rule)."""
    by_age = sorted(entries, key=lambda e: _when(e["at"]))
    order = [e for e in by_age if e.get("reported") is not None] + [
        e for e in by_age if e.get("reported") is None
    ]
    kept = list(entries)
    for entry in order:
        if len(kept) <= ENTRIES_MAX and log_bytes(kept) <= LOG_MAX_BYTES:
            break
        kept.remove(entry)
    return kept


def merge_logs(stored: list[dict], incoming: list[dict]) -> list[dict]:
    """The account's log and a device's, merged by entry: one in both keeps whichever changed
    last (the later day, then the higher `rev`); a tie keeps the reported copy, so a check-off is
    never lost, and otherwise the device's. Nothing is deleted from a log, only archived, so an
    entry missing from a device's copy is one it has not seen yet, and it stays. Both are `dated`
    first, so no copy brings a time of day back. Newest day first; within a day, in the device's
    order (newest first), then the account's."""
    stored = [dated(e) for e in stored]
    incoming = [dated(e) for e in incoming]
    rank: dict[str, int] = {}
    for entry in [*incoming, *stored]:
        rank.setdefault(entry["id"], len(rank))
    by_id: dict[str, dict] = {}
    for entry in stored:
        by_id[entry["id"]] = entry
    for entry in incoming:
        had = by_id.get(entry["id"])
        if had is None or _changed(entry) > _changed(had):
            won = entry
        elif _changed(entry) < _changed(had):
            won = had
        else:
            won = had if had.get("reported") and not entry.get("reported") else entry
        # A website looked up on one copy is kept whichever copy wins (a lookup is not a change).
        if had is not None and won.get("where") is None:
            won = {**won, "where": (had if won is entry else entry).get("where")}
        by_id[entry["id"]] = won
    merged = sorted(by_id.values(), key=lambda e: (-_when(e["at"]).toordinal(), rank[e["id"]]))
    return cap_log(merged)


# --- Which 311 ---------------------------------------------------------------------------


@cache
def _dc_rings() -> list[list[list[float]]]:
    shape = json.loads(DC_BOUNDARY.read_text())
    features = shape.get("features") if shape.get("type") == "FeatureCollection" else [shape]
    rings: list[list[list[float]]] = []
    for feature in features:
        geometry = feature.get("geometry", feature)
        coordinates = geometry["coordinates"]
        polygons = coordinates if geometry["type"] == "MultiPolygon" else [coordinates]
        for polygon in polygons:
            rings.extend(polygon)
    return rings


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_dc(lon: float, lat: float) -> bool:
    """Whether a point is inside DC (even-odd over every ring, so a hole is outside)."""
    return sum(_in_ring(lon, lat, ring) for ring in _dc_rings()) % 2 == 1


def _plain(name: str) -> str:
    name = name.casefold().replace("’", "'").strip()
    name = re.sub(r"^city of ", "", name)
    return re.sub(r" city$", "", name).strip()


def jurisdiction(state: str, county: str, city: str) -> str | None:
    """The 311 for Photon's state, county and city names, or None when the state is not one
    the log knows."""
    code = STATE_NAMES.get(state.casefold().strip())
    if code == "DC":
        return "dc"
    if code is None:
        return None
    county_name = county.casefold().replace("’", "'").strip()
    if county_name.endswith(" county"):
        found = COUNTIES[code].get(county_name.removesuffix(" county").strip())
        if found:
            return found
    elif county_name:
        # A county-equivalent with no "County": an independent city.
        found = CITIES[code].get(_plain(county_name))
        if found:
            return found
    elif city:
        found = CITIES[code].get(_plain(city))
        if found:
            return found
    return STATE_FALLBACK[code]


def where(lat: float, lon: float, *, lang: str) -> str | None:
    """Which 311 takes a point: "dc" inside DC, else from Photon's names for it.

    Raises geocode.Unavailable when Photon did not answer (the page asks again later)."""
    if in_dc(lon, lat):
        return "dc"
    names = geocode.area(lat, lon, lang=lang)
    if names is None:
        return None
    return jurisdiction(names.get("state", ""), names.get("county", ""), names.get("city", ""))
