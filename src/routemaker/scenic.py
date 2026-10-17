"""Scenic designations on a way, in words (v0.8.0, the Scenic map layer).

The owner, 2026-10-16: "Name in the road panel and have as a layer. Possibly the
scenic roads and trails layer. We could also add the east coast greenway and usbr
paths to that." Then: "Basically looking for a scenic layer in general. Off by
default. How about including covered bridges".

A designation is a fact about the way, never a stress input: nothing here is read
by the classifier or handed to the routing graph, and a scenic road keeps the tier
it would have had without it (no routing bonus). The rebuild writes the words onto
`segment.scenic` (`pipeline.scenic_layer`); the map draws a thin casing where it is
set and the road panel says it.

Where each designation comes from (docs/SOURCES.md):

- Montgomery County Rustic Roads and Exceptional Rustic Roads: Montgomery County
  Planning's Rustic Roads layer, `CLASSLABEL2`, matched to the ways it lies along.
- Maryland Scenic Byways: MDOT SHA's layer on MD iMAP, by byway name.
- The East Coast Greenway and the US Bicycle Routes: OSM route relations
  (`network=ncn`, `ref="USBR N"`; the Greenway is relation 1774795).
- Covered bridges: OSM `bridge=covered`, by the bridge's name.

Not included: Virginia's Rural Rustic Roads (a paving programme, no scenic layer
found), Virginia's Byways (VDOT asks for written permission) and Frederick
County's draft rustic roads (no licence).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# The words between designations: the road panel draws " · " and reads it as a comma.
SEPARATOR = " · "

# Montgomery County Planning's `CLASSLABEL2` values, to the panel's words.
MOCO_RUSTIC = "Rustic Road (Montgomery County)"
MOCO_EXCEPTIONAL = "Exceptional Rustic Road (Montgomery County)"
MOCO_CLASSES = {
    "rustic road": MOCO_RUSTIC,
    "exceptional rustic road": MOCO_EXCEPTIONAL,
}

EAST_COAST_GREENWAY = "East Coast Greenway"
# The Greenway's relation (docs/SOURCES.md); its state sections are named for it too.
EAST_COAST_GREENWAY_RELATION = 1774795
COVERED_BRIDGE = "Covered bridge"

# The installed reference rows' sources (`pipeline.scenic_layer`), and the credit
# each asks for, as the road panel names it.
MOCO_SOURCE = "moco-rustic"
MD_BYWAY_SOURCE = "md-byways"
SOURCES = {
    MOCO_SOURCE: "Montgomery County Planning",
    MD_BYWAY_SOURCE: "MDOT SHA",
}
OSM_CREDIT = "OpenStreetMap"

_USBR = re.compile(r"^\s*USBR\s*(\d+)\s*$", re.IGNORECASE)
# The name OSM's US Bicycle Route relations often carry instead of a USBR ref
# ("U.S. Bicycle Route 50", "US Bicycle Route 11").
_USBR_NAME = re.compile(r"^\s*U\.?\s?S\.?\s+Bicycle\s+Route\s+(\d+)\b", re.IGNORECASE)
_DIGITS = re.compile(r"^\s*(\d+)\s*$")
# The national network's `cycle_network` values (the USBR wiki: `US:US`; `US` is in use
# too). Not every value starting "US": a state route is `US:MD`, `US:VA`, with its own
# numbers, and a bare "50" there is not USBR 50.
NATIONAL_CYCLE_NETWORKS = frozenset({"US", "US:US"})
_BYWAY_SUFFIX = re.compile(r"\bbyway\s*$", re.IGNORECASE)


def moco_label(class_label: object) -> str | None:
    """A Rustic Roads record's words from its `CLASSLABEL2`, or None for any other value."""
    return MOCO_CLASSES.get(str(class_label or "").strip().casefold())


def byway_label(name: object) -> str | None:
    """'<name> Scenic Byway'; a name that already ends in 'Byway' is kept as it is."""
    text = " ".join(str(name or "").split())
    if not text:
        return None
    return text if _BYWAY_SUFFIX.search(text) else f"{text} Scenic Byway"


def usbr_number(tags: Mapping[str, str]) -> int | None:
    """The route number of a US Bicycle Route relation, as OSM tags it in three ways: a
    `ref="USBR N"`; a bare `ref=N` on the national network (`cycle_network` `US:US` or
    `US`, and `network=ncn`); or a name "U.S. Bicycle Route N". Each needs the national
    network (`network=ncn`, or a national `cycle_network`): a state or local route with a
    bare number is not a USBR. The East Coast Greenway (`cycle_network=US`, no number) has
    none."""
    national_cycle = (tags.get("cycle_network") or "").strip() in NATIONAL_CYCLE_NETWORKS
    ncn = tags.get("network") == "ncn"
    if not (ncn or national_cycle):
        return None
    ref = tags.get("ref") or ""
    found = _USBR.match(ref) or _USBR_NAME.match(tags.get("name") or "")
    if found is None and ncn and national_cycle:
        found = _DIGITS.match(ref)
    return int(found.group(1)) if found else None


def is_east_coast_greenway(relation_id: int, tags: Mapping[str, str]) -> bool:
    """The Greenway's relation, or a section named for it."""
    name = (tags.get("name") or "").strip().casefold()
    return relation_id == EAST_COAST_GREENWAY_RELATION or name.startswith(
        EAST_COAST_GREENWAY.casefold()
    )


def route_label(relation_id: int, tags: Mapping[str, str]) -> str | None:
    """A bicycle route relation's designation, or None for one that is not scenic here:
    'East Coast Greenway' (the relation, or a section named for it) or 'USBR N'."""
    routes = {part.strip() for part in (tags.get("route") or "").split(";")}
    if "bicycle" not in routes or tags.get("type") not in ("route", "superroute"):
        return None
    # The Greenway first and apart: it is on the national network too (`network=ncn`,
    # `cycle_network=US`) and must never read as a USBR.
    if is_east_coast_greenway(relation_id, tags):
        return EAST_COAST_GREENWAY
    number = usbr_number(tags)
    return f"USBR {number}" if number is not None else None


def covered_bridge_label(tags: Mapping[str, str]) -> str | None:
    """A covered bridge's name ('Roddy Road Covered Bridge'): its `bridge:name`, else its
    `name` where that names the bridge, else 'Covered bridge'. None if not `bridge=covered`
    (the wiki's tag; `covered=yes` is a roof over any way, not a covered bridge)."""
    if tags.get("bridge") != "covered":
        return None
    for key in ("bridge:name", "name"):
        value = " ".join((tags.get(key) or "").split())
        if value and (key == "bridge:name" or "bridge" in value.casefold()):
            return value
    return COVERED_BRIDGE


def _order(label: str) -> tuple[int, int, str]:
    """County, then byway, then the Greenway, then the USBRs by number, then a bridge."""
    if label in (MOCO_EXCEPTIONAL, MOCO_RUSTIC):
        return (0, 0 if label == MOCO_EXCEPTIONAL else 1, label)
    if label.endswith("Byway"):
        return (1, 0, label)
    if label == EAST_COAST_GREENWAY:
        return (2, 0, label)
    found = _USBR.match(label)
    if found:
        return (3, int(found.group(1)), label)
    return (4, 0, label)


def phrase(labels: Iterable[str | None]) -> str | None:
    """The designations as the road panel says them, each once, in a fixed order:
    'Rustic Road (Montgomery County) · East Coast Greenway · USBR 50'. None for none.
    A way along records of both kinds of rustic road says both, as the county's layer does."""
    kept = {label for label in labels if label}
    return SEPARATOR.join(sorted(kept, key=_order)) or None


def credits(text: str | None) -> str | None:
    """Who each designation in a phrase comes from, for the panel's source line."""
    if not text:
        return None
    found: list[str] = []
    for label in text.split(SEPARATOR):
        if label in (MOCO_RUSTIC, MOCO_EXCEPTIONAL):
            who = SOURCES[MOCO_SOURCE]
        elif label.endswith("Byway"):
            who = SOURCES[MD_BYWAY_SOURCE]
        else:
            who = OSM_CREDIT
        if who not in found:
            found.append(who)
    return "; ".join(found)


# --- the installer's half (`scripts/install_reference_data.py`) -------------------------

# Where a record's road name or byway name may be, first found wins: the layers' field
# names were not readable from the cloud build, so the installer looks for the usual ones
# and refuses a byway layer with none (`--byway-name-field` names it).
ROAD_NAME_FIELDS = (
    "ROAD_NAME",
    "RD_NAME",
    "ROADNAME",
    "LOCALROADNAME",
    "STREET_NAME",
    "NAME",
    "Name",
)
BYWAY_NAME_FIELDS = ("BYWAY_NAME", "Byway_Name", "BywayName", "BYWAY", "Byway", "NAME", "Name")


class LayerUnreadable(ValueError):
    """The layer has no field the installer needs."""


def _lines(geometry: Mapping | None):
    if not geometry:
        return
    if geometry.get("type") == "LineString":
        yield geometry["coordinates"]
    elif geometry.get("type") == "MultiLineString":
        yield from geometry["coordinates"]


def _first(properties: Mapping, fields: Iterable[str]) -> str | None:
    for field in fields:
        value = " ".join(str(properties.get(field) or "").split())
        if value:
            return value
    return None


def _feature_id(feature: Mapping, properties: Mapping, index: int) -> object:
    return properties.get("OBJECTID", feature.get("id", index))


def _row(source: str, key: object, part: int, label: str, name: str | None, line) -> dict:
    return {
        "id": f"{source}-{key}-{part}",
        "source": source,
        "label": label,
        "name": name,
        "coordinates": [[round(c[0], 7), round(c[1], 7)] for c in line],
    }


def rustic_rows(document: Mapping, name_field: str | None = None) -> tuple[list[dict], int]:
    """Montgomery County Planning's Rustic Roads layer as installed rows, and how many
    records were left out (a `CLASSLABEL2` that is neither kind, or no line). A layer with
    no road name in any record is refused: the name is what keeps a record off a parallel
    street or a differently named connector (`conflate_blocks`' name veto)."""
    features = list(document.get("features", ()))
    fields = (name_field,) if name_field else ROAD_NAME_FIELDS
    if features and not any(
        (f.get("properties") or {}).get(field) for f in features for field in fields
    ):
        raise LayerUnreadable(
            f"no road name in any of the fields {', '.join(fields)}: name the layer's "
            "field with --rustic-name-field"
        )
    rows, dropped = [], 0
    for index, feature in enumerate(features):
        properties = feature.get("properties") or {}
        label = moco_label(properties.get("CLASSLABEL2"))
        lines = list(_lines(feature.get("geometry")))
        if not label or not lines:
            dropped += 1
            continue
        key = _feature_id(feature, properties, index)
        name = _first(properties, fields)
        rows += [_row(MOCO_SOURCE, key, part, label, name, line) for part, line in enumerate(lines)]
    return rows, dropped


def byway_rows(document: Mapping, name_field: str | None = None) -> tuple[list[dict], int]:
    """MDOT SHA's Scenic Byways layer as installed rows, and how many records were left
    out (no name or no line). A record's name is its byway's, not its road's, so it is
    not compared with the way's name (`name` is None)."""
    features = list(document.get("features", ()))
    fields = (name_field,) if name_field else BYWAY_NAME_FIELDS
    if features and not any(
        (f.get("properties") or {}).get(field) for f in features for field in fields
    ):
        raise LayerUnreadable(
            f"no byway name in any of the fields {', '.join(fields)}: name the layer's "
            "field with --byway-name-field"
        )
    rows, dropped = [], 0
    for index, feature in enumerate(features):
        properties = feature.get("properties") or {}
        label = byway_label(_first(properties, fields))
        lines = list(_lines(feature.get("geometry")))
        if not label or not lines:
            dropped += 1
            continue
        key = _feature_id(feature, properties, index)
        rows += [
            _row(MD_BYWAY_SOURCE, key, part, label, None, line) for part, line in enumerate(lines)
        ]
    return rows, dropped
