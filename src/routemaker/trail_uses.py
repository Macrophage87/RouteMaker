"""Trails a land manager lists as open to bicycles (the owner, 2026-11-25, of Southwest
Florida: "Most of the trails that are advertised for biking are closed for biking").

The trail rules close a path that OSM leaves silent about bicycles where it is a hiking
route, a plain path in a park or a natural-surface path (`routemaker.trailaccess`): a
guess, made for the DC area's park paths, that "err closed" is the safe reading where
nothing says a bicycle may ride. Where the agency that manages the land publishes the
trail's allowed uses, that is no longer unclear: a trail it lists for biking is open,
whatever the closure rules would guess.

The source is the state's own record, read as data (`pipeline.trail_uses` matches it to
the ways): Florida's Office of Greenways and Trails "Existing Trails" layer (Florida
Department of Environmental Protection open data), whose `TYPE` field names each
trail's uses. A new state with such a record needs only a parser here. A way's own
`bicycle` tag always wins: a manager's list opens a silent way, never one OSM closes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

# The "Existing Trails" layer (OpenData/OGT/MapServer/3).
FL_OGT_SOURCE = "fl-ogt"
FL_OGT_URL = "https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/OGT/MapServer/3"
# The layer's uses that include riding a bicycle: any TYPE whose "/"-separated uses
# name Biking (Biking, Hiking/Biking, Biking/Equestrian, ...), and "Multi-Use", the
# layer's word for a shared-use trail (hiking, biking and skating). Hiking, Equestrian,
# Paddling and Off-Highway Vehicle trails are left as the tag rules read them.
FL_OGT_BIKING_USE = "Biking"
FL_OGT_SHARED_USE = "Multi-Use"


def is_biking_type(kind: str) -> bool:
    """True when an "Existing Trails" TYPE lists riding a bicycle."""
    uses = {use.strip().casefold() for use in kind.split("/")}
    return FL_OGT_BIKING_USE.casefold() in uses or FL_OGT_SHARED_USE.casefold() in uses


SOURCES = frozenset({FL_OGT_SOURCE})

# The way classes a trail record may open: the trail classes the closure rules read,
# and a track (a tram road through a preserve is mapped as one).
TRAIL_HIGHWAYS = frozenset({"path", "footway", "bridleway", "track", "cycleway"})


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def fl_ogt_rows(document: Mapping) -> tuple[list[dict], int]:
    """The biking trails of an "Existing Trails" query answer (ArcGIS JSON with
    geometry in lon/lat, or GeoJSON), one row per line part, and how many records were
    left out (not for bicycles, or with no line)."""
    rows: list[dict] = []
    dropped = 0
    for index, feature in enumerate(document.get("features") or ()):
        attributes = feature.get("attributes") or feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if "paths" in geometry:
            parts = geometry["paths"]
        elif geometry.get("type") == "LineString":
            parts = [geometry.get("coordinates") or []]
        elif geometry.get("type") == "MultiLineString":
            parts = geometry.get("coordinates") or []
        else:
            parts = []
        kind = _text(attributes.get("TYPE"))
        parts = [part for part in parts if len(part) >= 2]
        if not is_biking_type(kind) or not parts:
            dropped += 1
            continue
        record = attributes.get("OBJECTID", index)
        name = _text(attributes.get("SEGMENT_NAME")) or _text(attributes.get("TRAIL_NAME"))
        for n, part in enumerate(parts):
            rows.append(
                {
                    "id": f"{FL_OGT_SOURCE}-{record}-{n}",
                    "source": FL_OGT_SOURCE,
                    "uses": kind,
                    "name": name,
                    "site": _text(attributes.get("MANAGING_SITE")),
                    "coordinates": [[round(x, 6), round(y, 6)] for x, y, *_ in part],
                }
            )
    return rows, dropped


def opens(tags: Mapping[str, str]) -> bool:
    """Whether a manager's biking listing may open this way: a trail class OSM is silent
    about for bicycles, and no access tag that closes it to the public."""
    if tags.get("highway") not in TRAIL_HIGHWAYS or "bicycle" in tags:
        return False
    return tags.get("access") in (None, "yes", "permissive", "designated")


def candidates(ways: Iterable) -> list:
    """The ways `opens` lets a listing reach."""
    return [way for way in ways if opens(way.tags)]
