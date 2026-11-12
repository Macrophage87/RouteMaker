"""Facts changed since rated: the roads whose facts moved under a level we pinned.

An own-picks row (`fixtures/overrides/2026-11-09-owner-*-own-picks.json`) sets a road's
level above the formula, and before this the rebuild noticed only when the way's line,
name or class changed (`pipeline.rematch.drift`). A new protected lane, a lower posted
speed, a new count or more lanes left the pinned level standing and nobody was told
(backlog 2026-11-12, area 02 item 1).

Each own-picks group already records the facts it was rated from, in its `evidence`
sentence ("residential, rural, speed 25 posted, lanes 2, two way, 1,500-2,999, facility
none"). A row or group may instead carry them as a `facts` object (`FACT_KEYS`), which is
read first; the sentence is the fallback the 2026-11-09 files need. At each rebuild the
stored facts are compared with what this extract and the agency layers now say about the
way (`changes`), and every way whose facts moved is written to
`reports/rated-facts-changed.{md,csv}` for the Review queue "Facts changed since rated"
(`core.stress_review`). A report, never a stage's output: the level stays ours until
someone re-rates the road (our default; the owner's call is open, 2026-11-12).

What counts as a change, and the margins (our defaults, unmeasured):
- class: the OSM `highway` class (without `_link`) is different;
- speed: a speed is now read where none was, or none where one was, or it moved by
  `SPEED_STEP_MPH` or more;
- lanes: the `lanes` tag's total is different (a tag gained or lost counts);
- count: a count now exists where the road had none, or lies outside its stored band by
  more than `COUNT_MARGIN` (a road that lost its count is not listed: the road did not
  change, the match did);
- facility: the bike facility class (path, protected, lane, none) is different.
One-way and the Census urban flag are not compared: neither changes on its own, and the
sweep read them in ways the rebuild cannot reproduce exactly.
"""

from __future__ import annotations

import csv
import functools
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .rematch import OVERRIDES_DIR

REPORT_NAME = "rated-facts-changed"

# The facts a row may carry as an object, and what each holds.
#   highway: OSM class as rated ("residential"); urban: bool;
#   speed_mph: int or None (None = no speed read); speed_source: "posted", "agency", or None;
#   lanes: int or None (the `lanes` tag's total); oneway: bool;
#   count_band: [low, high] cars a day (high None = open-ended), or None (no count);
#   facility: "path", "protected", "lane" or "none".
FACT_KEYS = frozenset(
    {"highway", "urban", "speed_mph", "speed_source", "lanes", "oneway", "count_band", "facility"}
)
FACILITIES = ("path", "protected", "lane", "none")

# Our defaults, unmeasured: a speed reading this far from the stored one is a change (a
# 5 mph step is one posted-sign step), and a count this far outside its band.
SPEED_STEP_MPH = 5
COUNT_MARGIN = 0.2

_EVIDENCE = re.compile(
    r"group G\d+: (?P<highway>[a-z_]+)(?::[a-z_]+)?, (?P<setting>rural|urban), "
    r"speed (?:none|(?P<speed>\d+) (?P<source>posted|agency/other|default)), "
    r"lanes (?:None|(?P<lanes>\d+)), (?P<way>one|two) way, "
    r"(?P<count>no count|<[\d,]+|[\d,]+-[\d,]+|[\d,]+\+), "
    r"facility (?P<facility>path|protected|lane|none)\b"
)


OWN_PICKS_HEAD = "Own-picks review "


def _number(text: str) -> int:
    return int(text.replace(",", ""))


def count_band(text: str) -> list | None:
    """'1,500-2,999' -> [1500, 2999]; '<500' -> [0, 499]; '30,000+' -> [30000, None];
    'no count' -> None."""
    if text == "no count":
        return None
    if text.startswith("<"):
        return [0, _number(text[1:]) - 1]
    if text.endswith("+"):
        return [_number(text[:-1]), None]
    low, high = text.split("-")
    return [_number(low), _number(high)]


def from_evidence(sentence: str) -> dict | None:
    """The facts an own-picks group's evidence sentence states, or None where the
    sentence is not in that form (a hand-written row's)."""
    # Only an own-picks review's own sentence: a later row that quotes one (Woodglen Drive's,
    # 2026-11-10, replaced because those facts were wrong) is not rated from it.
    m = _EVIDENCE.search(sentence or "") if (sentence or "").startswith(OWN_PICKS_HEAD) else None
    if not m:
        return None
    source = m["source"]
    speed = int(m["speed"]) if m["speed"] and source != "default" else None
    return {
        "highway": m["highway"],
        "urban": m["setting"] == "urban",
        "speed_mph": speed,
        "speed_source": None if speed is None else ("posted" if source == "posted" else "agency"),
        "lanes": int(m["lanes"]) if m["lanes"] else None,
        "oneway": m["way"] == "one",
        "count_band": count_band(m["count"]),
        "facility": m["facility"],
    }


def facts_problem(facts: object) -> str | None:
    """Why `facts` is not a facts object (`FACT_KEYS`), or None."""
    if not isinstance(facts, dict):
        return "facts is an object"
    extra = set(facts) - FACT_KEYS
    if extra:
        return f"facts has no {sorted(extra)}; its keys are {sorted(FACT_KEYS)}"
    for key in ("highway", "speed_source"):
        if facts.get(key) is not None and not isinstance(facts[key], str):
            return f"facts.{key} is text or null"
    for key in ("urban", "oneway"):
        if key in facts and not isinstance(facts[key], bool):
            return f"facts.{key} is true or false"
    if "facility" in facts and facts["facility"] not in FACILITIES:
        return f"facts.facility is one of {list(FACILITIES)}"
    for key in ("speed_mph", "lanes"):
        value = facts.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            return f"facts.{key} is a whole number or null"
    band = facts.get("count_band")
    if band is not None and not (
        isinstance(band, list)
        and len(band) == 2
        and isinstance(band[0], int)
        and (band[1] is None or isinstance(band[1], int))
    ):
        return "facts.count_band is [low, high] (high may be null) or null"
    return None


@dataclass(frozen=True)
class Rated:
    """What a pinned row was rated from: its facts, its file, the day it was decided, and its
    `adjustment_id`, so the facts are compared only while that row is the one applied."""

    facts: dict
    file: str
    decided: str
    reason: str = ""
    adjustment_id: str | None = None


def load(directory: Path | str | None = None) -> dict[int, Rated]:
    """{way id: Rated} for every stress row or group in the override files that states
    its facts (a `facts` object, else an own-picks evidence sentence). About two seconds
    over the own-picks files, so kept while the files are unchanged (`_load`)."""
    paths = sorted(Path(directory or OVERRIDES_DIR).glob("*.json"))
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
    return dict(_load(signature))


@functools.lru_cache(maxsize=2)
def _load(signature: tuple) -> dict[int, Rated]:
    found: dict[int, Rated] = {}
    for name, _mtime, _size in signature:
        path = Path(name)
        try:
            document = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict):
            continue
        decided = str(document.get("decided") or "")
        # A row a later file retires (its `retire` list, matched by adjustment id) no longer
        # pins the way with its facts. The row written in its place is checked only if it
        # states facts of its own: a replacement is often made because the facts were wrong
        # (Woodglen Drive's protected lane, 2026-11-10), so it never inherits the old ones.
        for entry in document.get("retire") or []:
            if not isinstance(entry, dict) or entry.get("kind") != "stress":
                continue
            way = entry.get("osm_way_id")
            value = entry.get("value") if isinstance(entry.get("value"), dict) else {}
            old = found.get(way)
            if old is not None and old.adjustment_id == value.get("adjustment_id"):
                del found[way]
        entries = [
            (row, [row.get("osm_way_id")])
            for row in document.get("rows") or []
            if isinstance(row, dict)
        ] + [
            (group, group.get("ways") or [])
            for group in document.get("groups") or []
            if isinstance(group, dict)
        ]
        for entry, ways in entries:
            if entry.get("kind") != "stress":
                continue
            facts = entry.get("facts")
            if facts is None or facts_problem(facts):
                facts = from_evidence(entry.get("evidence") or "")
            value = entry.get("value") if isinstance(entry.get("value"), dict) else {}
            adjustment = value.get("adjustment_id")
            reason = str(entry.get("reason") or "")
            rated = Rated(facts, path.name, decided, reason, adjustment) if facts else None
            if rated is None:
                continue
            for way in ways:
                if isinstance(way, int) and not isinstance(way, bool):
                    found[way] = rated
    return found


def follow_rematch(rated: Mapping[int, Rated], entries: Iterable) -> dict[int, Rated]:
    """`rated` with each re-matched row's facts carried to the ways it now stands on
    (`pipeline.rematch` report entries: `old_way_id`, `new_way_ids`, `kind`)."""
    out = dict(rated)
    for entry in entries:
        if getattr(entry, "kind", None) != "stress" or entry.old_way_id not in rated:
            continue
        for new in getattr(entry, "new_way_ids", ()) or ():
            out.setdefault(new, rated[entry.old_way_id])
    return out


def current_facts(tags: Mapping[str, str], result, facility_class: str | None) -> dict:
    """The facts this extract and the agency layers give the way now, in the stored form.

    `result` is the classifier's `routemaker.stress.StressResult` (before any row): its
    `speed_mph` is the speed read (a tag, an agency's record, a curated speed; None where
    assumed), its `volume_aadt` the count."""
    lanes = tags.get("lanes")
    try:
        lanes_n = int(str(lanes).split(";")[0]) if lanes is not None else None
    except ValueError:
        lanes_n = None
    speed = getattr(result, "speed_mph", None)
    return {
        "highway": str(tags.get("highway") or ""),
        "speed_mph": None if speed is None else int(round(speed)),
        "lanes": lanes_n,
        "count": getattr(result, "volume_aadt", None),
        "facility": facility_class or "none",
    }


def _band_words(band) -> str:
    if band is None:
        return "no count"
    low, high = band
    if high is None:
        return f"{low:,}+ a day"
    return f"{low:,}-{high:,} a day"


def _base(highway: str) -> str:
    return (highway or "").replace("_link", "")


def changes(stored: Mapping, now: Mapping) -> list[str]:
    """What moved between the stored facts and `now` (`current_facts`), in words; empty
    where nothing that counts did (the module docstring)."""
    out: list[str] = []
    if (
        stored.get("highway")
        and now.get("highway")
        and _base(stored["highway"]) != _base(now["highway"])
    ):
        out.append(f"class {stored['highway']} -> {now['highway']}")
    was, is_ = stored.get("speed_mph"), now.get("speed_mph")
    if was is None and is_ is not None:
        out.append(f"speed now read: {is_} mph (none when rated)")
    elif was is not None and is_ is None:
        out.append(f"speed {was} mph when rated, none read now")
    elif was is not None and abs(was - is_) >= SPEED_STEP_MPH:
        out.append(f"speed {was} -> {is_} mph")
    if "lanes" in stored and stored.get("lanes") != now.get("lanes"):
        out.append(f"lanes {stored.get('lanes') or 'untagged'} -> {now.get('lanes') or 'untagged'}")
    band, count = stored.get("count_band"), now.get("count")
    if count is not None:
        if band is None:
            out.append(f"count now {count:,} a day (none when rated)")
        else:
            low, high = band
            if count < low * (1 - COUNT_MARGIN) or (
                high is not None and count > high * (1 + COUNT_MARGIN)
            ):
                out.append(f"count {_band_words(band)} -> {count:,} a day")
    if stored.get("facility") and stored["facility"] != now.get("facility"):
        out.append(f"bike facility {stored['facility']} -> {now.get('facility')}")
    return out


@dataclass
class Changed:
    way_id: int
    name: str
    highway: str
    our_level: float | None
    formula_level: float | None
    rated: Rated
    what: list[str] = field(default_factory=list)


def report_csv(rows: list[Changed]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["way_id", "name", "highway", "our_level", "formula_level", "rated", "file", "reason"]
    )
    for r in rows:
        writer.writerow(
            [
                r.way_id,
                r.name,
                r.highway,
                "" if r.our_level is None else r.our_level,
                "" if r.formula_level is None else r.formula_level,
                r.rated.decided,
                r.rated.file,
                "Facts changed since rated: " + "; ".join(r.what),
            ]
        )
    return out.getvalue()


def report_markdown(rows: list[Changed], checked: int) -> str:
    lines = [
        "# Facts changed since rated",
        "",
        "Written by the rebuild (`pipeline.rated_facts`). Each road below carries a level we "
        "pinned (an own-picks or other reviewed stress row that states the facts it was rated "
        "from), and something those facts said has changed in this build's data. The road "
        "keeps our level (our default) until someone re-rates it; the formula's level today is "
        "beside it for comparison.",
        "",
        f"- Pinned roads with stored facts, in this extract: {checked}",
        f"- Facts changed: {len(rows)}",
        "",
    ]
    if rows:
        lines += [
            "| Way | Street | Class | Our level | Formula now | Rated | What changed |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            ours = "" if r.our_level is None else r.our_level
            formula = "" if r.formula_level is None else r.formula_level
            lines.append(
                f"| {r.way_id} | {r.name} | {r.highway} | {ours} | {formula} "
                f"| {r.rated.decided} | {'; '.join(r.what)} |"
            )
    return "\n".join(lines) + "\n"


def compare(
    rated: Mapping[int, Rated],
    ways_by_id: Mapping[int, object],
    stress_by_way: Mapping[int, object],
    our_level: Mapping[int, float],
    facility_of,
    formula_of,
) -> tuple[list[Changed], int]:
    """The pinned ways whose facts moved, and how many pinned ways were checked.

    `stress_by_way` is the classifier's result before any row; `our_level` the level each
    pinned row sets; `facility_of(way_id, tags)` the facility class from the tags the
    classifier read (the agency overlay and curated lanes included); `formula_of(result)`
    the formula's own level. Class and `lanes` are the way's own OSM tags, as the
    own-picks sweep read them. A way whose stored facts cannot be compared is skipped."""
    out: list[Changed] = []
    checked = 0
    for way_id, r in rated.items():
        way = ways_by_id.get(way_id)
        result = stress_by_way.get(way_id)
        if way is None or result is None:
            continue
        checked += 1
        tags = getattr(way, "tags", {}) or {}
        try:
            what = changes(r.facts, current_facts(tags, result, facility_of(way_id, tags)))
        except (TypeError, ValueError, AttributeError):
            continue
        if what:
            out.append(
                Changed(
                    way_id=way_id,
                    name=str(tags.get("name") or ""),
                    highway=str(tags.get("highway") or ""),
                    our_level=our_level.get(way_id),
                    formula_level=formula_of(result),
                    rated=r,
                    what=what,
                )
            )
    out.sort(key=lambda c: (c.name, c.way_id))
    return out, checked
