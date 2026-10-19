"""Known road hazards the map marks (v0.10.0). The owner, 2026-10-19: "We should have a
symbol for roads with known other hazards on the map. One example is the cobblestones in
Georgetown or the streetcar rails on H street".

Two kinds, each a fact a rider wants to know before reaching it:

- `cobbles`: a road paved in granite setts or cobblestones (OSM `surface=sett`,
  `cobblestone`, `cobblestone:flattened` or `unhewn_cobblestone`). Georgetown's O and
  P Streets NW are relaid setts (DDOT's O and P Streets Rehabilitation Project).
- `rails`: rails set in the road a wheel can drop into or slide on: a street-running
  tram or streetcar line (OSM `railway=tram`, an `embedded=yes` railway, a disused
  tram line whose rails are still there) along the road, or a road tagged
  `embedded_rails`. DC Streetcar's H Street NE and Benning Road NE line closed on
  31 March 2026 and its rails are still in the street.

Where OSM misses one, a reviewed entry in `fixtures/hazards/` adds it (`load`).

Display only: nothing here is read by the classifier or the graph, so a marked road keeps
its stress and its routing (`segment.is_rough` and the surface pricing already treat
cobblestones as they always have). The map draws a symbol along the way
(frontend/src/lib/hazardLayer.ts) and the road panel says the hazard in words
(`core.segment_info`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

HAZARDS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "hazards"

COBBLES = "cobbles"
RAILS = "rails"
KINDS = (COBBLES, RAILS)

# The road panel's words, one short line each.
WORDS = {
    COBBLES: "Cobblestones: bumpy, and slippery when wet",
    RAILS: "Rails in the road: cross them square on, a wheel can drop into the groove",
}

# Who says so: OSM's tags and lines, or the reviewed list (`fixtures/hazards/`).
OSM_CREDIT = "OpenStreetMap"
LIST_CREDIT = "RouteMaker's hazard list"
# The column marks a hand-listed kind with this suffix ("rails/list").
LISTED = "/list"

COBBLE_SURFACES = frozenset({"sett", "cobblestone", "cobblestone:flattened", "unhewn_cobblestone"})

# A railway way whose rails lie in a road: a tram line runs in the street by definition in
# this region (DC Streetcar), and any other line only where OSM says `embedded`. A disused
# line counts when it was a tram (its rails stay until removed); an abandoned or razed one
# has no rails left and never counts.
TRAM_RAILWAYS = frozenset({"tram"})
DISUSED_RAILWAYS = frozenset({"disused"})
NO_RAILS = frozenset({"abandoned", "razed", "dismantled", "proposed", "construction"})


def way_kinds(tags: Mapping[str, str]) -> set[str]:
    """The hazards a highway way's own tags say it has."""
    found = set()
    if (tags.get("surface") or "").strip() in COBBLE_SURFACES:
        found.add(COBBLES)
    embedded = (tags.get("embedded_rails") or "").strip()
    if embedded and embedded != "no":
        found.add(RAILS)
    if (tags.get("railway") or "").strip() in TRAM_RAILWAYS:
        # A road mapped with its tram line on the same way.
        found.add(RAILS)
    return found


def is_street_rail(tags: Mapping[str, str]) -> bool:
    """Whether a railway way's rails are set in a street (`pipeline.hazard_layer`)."""
    railway = (tags.get("railway") or "").strip()
    if not railway or railway in NO_RAILS:
        return False
    if (tags.get("embedded") or "").strip() == "yes":
        return True
    if railway in TRAM_RAILWAYS:
        return True
    if railway in DISUSED_RAILWAYS:
        return (tags.get("disused:railway") or "").strip() in TRAM_RAILWAYS or tags.get(
            "tram"
        ) == "yes"
    return False


def encode(osm: Iterable[str], listed: Iterable[str] = ()) -> str | None:
    """`segment.hazard`: the kinds in KINDS order, a hand-listed one (not also OSM's)
    marked LISTED; None for none. The map reads the kinds by substring."""
    osm, listed = set(osm), set(listed)
    parts = [k if k in osm else k + LISTED for k in KINDS if k in osm or k in listed]
    return ",".join(parts) or None


def decode(text: str | None) -> list[tuple[str, bool]]:
    """(kind, hand-listed) for each kind in the column, unknown ones left out."""
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        listed = part.endswith(LISTED)
        kind = part[: -len(LISTED)] if listed else part
        if kind in WORDS:
            out.append((kind, listed))
    return out


def words(text: str | None) -> str | None:
    """The panel's line for the column, or None."""
    kinds = decode(text)
    return "; ".join(WORDS[kind] for kind, _ in kinds) or None


def credits(text: str | None) -> str | None:
    kinds = decode(text)
    if not kinds:
        return None
    names = []
    if any(not listed for _, listed in kinds):
        names.append(OSM_CREDIT)
    if any(listed for _, listed in kinds):
        names.append(LIST_CREDIT)
    return " and ".join(names)


# --- The reviewed list ------------------------------------------------------------------


class HazardListRefused(ValueError):
    """A hazard-list file that is wrong, or a folder that is missing."""


@dataclass(frozen=True)
class ListedHazard:
    """One reviewed entry: its kinds, and where. Either OSM way ids, or a street by its
    OSM name between two cross streets (each found where the street's ways share a node
    with a way of that name), or both."""

    id: str
    kinds: tuple[str, ...]
    source: str
    ways: tuple[int, ...] = ()
    street: str | None = None
    between: tuple[str, str] | None = None


def parse(document: dict, name: str = "hazard list file") -> list[ListedHazard]:
    out = []
    for entry in document.get("hazards", []):
        try:
            between = entry.get("between")
            item = ListedHazard(
                id=str(entry["id"]),
                kinds=tuple(entry["kinds"]),
                source=str(entry["source"]),
                ways=tuple(int(w) for w in entry.get("ways", ())),
                street=entry.get("street"),
                between=(str(between[0]), str(between[1])) if between else None,
            )
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise HazardListRefused(f"{name}: a bad entry ({error!r})") from error
        if not item.kinds or any(k not in KINDS for k in item.kinds):
            raise HazardListRefused(f"{name}: {item.id} needs kinds from {KINDS}")
        if not item.source.strip():
            raise HazardListRefused(f"{name}: {item.id} needs a source")
        if bool(item.street) != bool(item.between):
            raise HazardListRefused(f"{name}: {item.id}: a street needs `between`, and back")
        if not item.ways and not item.street:
            raise HazardListRefused(f"{name}: {item.id} names no way and no street")
        out.append(item)
    return out


def load(directory: Path | str | None = None) -> list[ListedHazard]:
    """Every entry in every file of the folder. A missing folder is refused (the pipeline
    image copies `fixtures/`), as for the lane overrides."""
    folder = Path(directory or HAZARDS_DIR)
    if not folder.is_dir():
        raise HazardListRefused(f"the hazard-list folder {folder} does not exist")
    entries: list[ListedHazard] = []
    for path in sorted(folder.glob("*.json")):
        entries.extend(parse(json.loads(path.read_text()), path.name))
    ids = [e.id for e in entries]
    if len(set(ids)) != len(ids):
        raise HazardListRefused("hazard list ids must be unique across files")
    return entries
