"""Maryland's road closures as its counties and towns report them: MDOT SHA's Road Closure
Reporter (v0.17.0).

Stephen, 2026-11-01, on the closure-sources survey: these are "Real closures, routed round".
The Reporter is where Maryland's counties and towns (Baltimore County, Frederick, Harford,
Anne Arundel, Prince George's and others; Montgomery, Howard and Baltimore City do not report
there) post a closure on their own roads, which the state's WZDx feed (source "md") does not
carry. Each record is one stretch of road with its own start and end to the second, so a
closure is routed round only while it is in force (`workzones.active`), like a WZDx zone.

Two layers, read alike: closures in force now (RoadClosureActive) and those posted to come
(RoadClosurePlanned). Each record is a line along the road, one of several where a closure
runs over more than one stretch (they share the closure's `RC_GUID`).

What a record's `ClosureType` and `closureSummary` mean for a bicycle:

- "Closed", or "Emergency Vehicle Only Access" (a crash, the Key Bridge): closed, routed
  round (one direction only: every lane closed, a heavy penalty).
- "Limited Public Access" with every lane closed (local traffic only, a project's road): every
  lane closed and bicycles not mentioned, as a WZDx zone with all lanes closed
  (`workzones.UNKNOWN`): a heavy penalty, so a reasonable way round is taken (one direction
  only: a lane penalty).
- A lane closed and the road open ("1 lane(s) open", "Curb Lane Closure"): a lane penalty.

Only the closure's own fields are asked for: never its `Creator` (the reporting account); a
phone number or email in an agency's comments is never kept.

Pure: no network, no database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime

from . import planned_work as pw
from . import workzones as wz

SHA = "sha"
# The fields asked for: never `Creator`, `CreationDate` or `EditDate`.
FIELDS = (
    "OBJECTID,RC_GUID,ClosureStart,ClosureEnd,ClosureType,Comments,RoadName,CrossStreet1,"
    "CrossStreet2,Jurisdiction,closureSummary"
)

CLOSED_TYPES = frozenset({"closed", "emergency vehicle only access"})
ALL_LANES = re.compile(r"all lanes closed", re.I)
DIRECTION = re.compile(r":\s*[^,]*,\s*(northbound|southbound|eastbound|westbound)", re.I)
ALL_WAYS = re.compile(r"all directions", re.I)
MAX_DESCRIPTION = 300
# A contact in an agency's free text: never kept.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\(?\b\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{4}\b")
# Kept in capitals in a road's name.
CAPITALS = frozenset({"MD", "US", "I", "NB", "SB", "EB", "WB", "JFK", "NW", "NE", "SW", "SE"})


def _tidy(text) -> str:
    return " ".join(str(text or "").split())


def classify(closure_type: str, summary: str) -> tuple[str, float, str]:
    """(kind, penalty seconds, why) for a record's type and summary. A closure of one
    direction ("Closed, Northbound") is a step lighter, since its line carries no direction
    and the other way stays open: closed becomes every lane closed (a heavy penalty), every
    lane closed a lane penalty."""
    kind = _tidy(closure_type).lower()
    every_lane = bool(ALL_LANES.search(summary or ""))
    one_way = bool(DIRECTION.search(summary or "")) and not ALL_WAYS.search(summary or "")
    if kind in CLOSED_TYPES:
        if one_way:
            return wz.UNKNOWN, wz.UNKNOWN_PENALTY_S, "closed one way; the other way open"
        return wz.CLOSED, 0.0, "the road is closed"
    if every_lane and not one_way:
        return wz.UNKNOWN, wz.UNKNOWN_PENALTY_S, "every lane closed; bicycles not mentioned"
    if every_lane:
        return wz.PENALTY, wz.LANE_PENALTY_S, "every lane closed one way"
    return wz.PENALTY, wz.LANE_PENALTY_S, "a lane closed"


def _street(value) -> str:
    """A road as typed, in title case where it was typed in capitals ("MD 7" kept)."""
    text = _tidy(value)
    if not text.isupper():
        return text
    return " ".join(w if w in CAPITALS else w.capitalize() for w in text.split())


def _no_contacts(text: str) -> str:
    return PHONE.sub("[phone]", EMAIL.sub("[email]", text))


def _guid(value) -> str:
    """'{BF2850A2-E422-...}' -> 'bf2850a2-e422-...'."""
    return re.sub(r"[^0-9a-f-]", "", str(value or "").lower())


def parse_sha(documents: Iterable[Mapping], now: datetime) -> list[wz.Zone]:
    """The Reporter's closures not yet over, from its layers (GeoJSON, in force and to come),
    one zone a line: `sha-<closure>-<n>`, numbered along the ground, so a
    closure's stretches group as one on the map (the Key Bridge is 69 of them). A stretch in
    both layers is read once."""
    seen: set[tuple] = set()
    found: dict[str, list[tuple[tuple, dict]]] = {}
    for document in documents:
        for feature in document.get("features") or []:
            if not isinstance(feature, Mapping):
                continue
            props = feature.get("properties") or {}
            objectid = props.get("OBJECTID")
            if not isinstance(objectid, int) or isinstance(objectid, bool):
                continue
            end = pw._ms(props.get("ClosureEnd"))
            if end is None or end <= now:
                continue
            guid = _guid(props.get("RC_GUID")) or f"r{objectid}"
            for line in pw._lines(feature.get("geometry")):
                # The same stretch in both layers (the two are separate tables) is read once.
                key = (guid, props.get("ClosureStart"), props.get("ClosureEnd"), line)
                if key in seen:
                    continue
                seen.add(key)
                found.setdefault(guid, []).append(
                    ((line[0], line[-1]), {"props": props, "line": line})
                )
    zones = []
    for guid, pieces in found.items():
        # Numbered in the order of their lines on the ground, not of the records, so an id
        # names the same stretch when a closure is posted again.
        for index, (_, piece) in enumerate(sorted(pieces, key=lambda p: p[0])):
            zones.append(_zone(f"sha-{guid}-{index}", piece["props"], piece["line"]))
    return zones


def _zone(zone_id: str, props: Mapping, line) -> wz.Zone:
    summary = _tidy(props.get("closureSummary"))
    kind, penalty, why = classify(props.get("ClosureType"), summary)
    road = _street(props.get("RoadName")) or None
    direction = DIRECTION.search(summary)
    if road and direction:
        road = f"{road} {direction.group(1).lower()}"
    a, b = (_street(props.get(k)) for k in ("CrossStreet1", "CrossStreet2"))
    stretch = f"{road}, {a} to {b}" if road and a and b else road or "A road"
    place = _street(props.get("Jurisdiction"))
    what = _tidy(props.get("ClosureType")) or "Closure"
    comments = _no_contacts(_tidy(props.get("Comments")))
    description = "; ".join(t for t in (comments, summary) if t)[:MAX_DESCRIPTION]
    return wz.Zone(
        zone_id=zone_id,
        source=SHA,
        kind=kind,
        penalty_s=penalty,
        line=line,
        road=road,
        description=description or None,
        start=pw._ms(props.get("ClosureStart")),
        end=pw._ms(props.get("ClosureEnd")),
        reason=why,
        title=f"{stretch}: {what.lower()}" + (f" ({place})" if place else ""),
        url=wz.SOURCE_LINKS[SHA],
    )


__all__ = ["FIELDS", "SHA", "classify", "parse_sha"]
