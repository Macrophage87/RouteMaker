"""DDOT's Pavement Condition Index as the smoothness reading of a District street (DC-PCI).

The owner, 2026-10-11, adding it to the rebuild: "DC score in most cases takes
priority over OSM data" (the standing rule that the District's own data beats
OSM's). The source is DC GIS's `DDOT/PavementConditionIndex` FeatureServer,
polyline layers FY-12 to FY-25; the rebuild reads FY-25, layer 5 (`LAYER_URL`).
Its fields, read from the service's metadata on 2026-10-11, include `PCI` (0 to
100), `PCICTEGORY` (the layer's own spelling; "Good", "Excellent", ...),
`ROUTENAME`, `FROMSTREET`/`TOSTREET`, `ROUTEID`, `FROMMEASURE`/`TOMEASURE` and
three date fields: `DATE1`, `CONST_DATE` and `LSTMJRWRKD`. The service labels
none of them; `DATE1` is the one set on the records read (late February and
early March 2026), so it is taken as the survey date. That is an assumption,
recorded in docs/SOURCES.md for the owner to confirm. Where it is empty the
fiscal year's last day stands in (`fiscal_year_end`).

The reading, the owner's defaults as proposed for this item:

- PCI 70 and over: good. No penalty; and OSM's `smoothness` no longer speaks
  for the street (the graph drops it).
- 55 to 69: fair, a small penalty: the street is priced as the paved-but-rough
  class (cobblestone), upstream's reading of `smoothness=intermediate`.
- Under 55: poor, rough: the compacted class, upstream's reading of
  `smoothness=bad` and the roughest a penalty may make a way
  (lua/routemaker_remap.lua, `M.PCI_SURFACE`).

"In most cases" leaves two exceptions, both defaults for the owner to confirm:

- an approved RouteMaker correction wins: a row in `fixtures/pavement/overrides.json`
  for the way (`load_overrides`), either keeping OSM's reading or setting a band;
- an OSM `smoothness` edited after the segment's PCI survey wins. The extract
  carries one timestamp per way, its last edit of any kind, not per tag, so the
  test is that the way carries `smoothness` and was last edited after the survey.
  A later edit to the way's name also passes it; reading the tag's own history
  would need the full-history planet file, which the rebuild does not fetch.

Streets only, as far as the layer goes: a way of a street class
(`STREET_HIGHWAYS`). Alleys (`highway=service`), trails and paths keep OSM's
reading whatever lies near them.

Pure: the rebuild (`pipeline.run`) matches the layer's blocks to ways with
`conflation.conflate_blocks` and asks `resolve` per way.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

LAYER_URL = (
    "https://rh.dcgis.dc.gov/dcgis/rest/services/DDOT/PavementConditionIndex/FeatureServer/5"
)
FISCAL_YEAR = 2025
AGENCY = "ddot-pci"
CREDIT = "DDOT Pavement Condition Index (DC GIS)"

# Whether the owner has confirmed the layer's licence (docs/SOURCES.md, "DDOT
# Pavement Condition Index"). The service states none (read 2026-10-11), so until
# the owner confirms the terms with DDOT or Open Data DC nothing derived from it may
# reach the live router: the installer refuses `--dc-pci` and the rebuild ignores
# an installed `pavement.json` while this is False. Set it True in the commit that
# records the confirmation (its source and date) in docs/SOURCES.md.
LICENCE_CONFIRMED = False
LICENCE_PENDING = (
    "DDOT's Pavement Condition Index states no licence, and the owner has not yet "
    "confirmed one (docs/SOURCES.md, routemaker.pavement.LICENCE_CONFIRMED)"
)

GOOD_AT = 70.0
FAIR_AT = 55.0
GOOD, FAIR, POOR = "good", "fair", "poor"
BANDS = (GOOD, FAIR, POOR)

# The street classes the reading applies to. Not `service`: DC's alleys are
# service ways, and the owner keeps OSM's reading on alleys and trails.
STREET_HIGHWAYS = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
    }
)

# Surfaces a PCI may describe. A street tagged gravel or dirt is not one the
# District's pavement survey speaks for, whatever lies near it.
UNPAVED_SURFACES = frozenset(
    {"unpaved", "gravel", "fine_gravel", "compacted", "dirt", "earth", "ground", "grass", "sand",
     "mud", "pebblestone", "woodchips"}
)  # fmt: skip

OVERRIDES = Path(__file__).resolve().parents[2] / "fixtures" / "pavement" / "overrides.json"
KEEP_OSM = "osm"


def band(pci: float | None) -> str | None:
    """The owner's reading of a PCI: good, fair or poor; None without one."""
    if pci is None:
        return None
    if pci >= GOOD_AT:
        return GOOD
    if pci >= FAIR_AT:
        return FAIR
    return POOR


def fiscal_year_end(fiscal_year: int) -> date:
    """The District's fiscal year ends on 30 September (FY-25: 2025-09-30)."""
    return date(fiscal_year, 9, 30)


@dataclass(frozen=True)
class Block:
    """One surveyed block of the layer."""

    feature_id: str
    coordinates: Sequence[tuple[float, float]]
    pci: float
    name: str | None
    surveyed: date
    category: str | None = None
    route_id: str | None = None
    from_street: str | None = None
    to_street: str | None = None

    def to_json(self) -> dict:
        return {
            "id": self.feature_id,
            "coordinates": [list(c) for c in self.coordinates],
            "pci": self.pci,
            "name": self.name,
            "surveyed": self.surveyed.isoformat(),
            "category": self.category,
            "route_id": self.route_id,
            "from_street": self.from_street,
            "to_street": self.to_street,
        }

    @classmethod
    def from_json(cls, row: Mapping) -> Block:
        return cls(
            feature_id=row["id"],
            coordinates=[tuple(c) for c in row["coordinates"]],
            pci=float(row["pci"]),
            name=row.get("name"),
            surveyed=date.fromisoformat(row["surveyed"]),
            category=row.get("category"),
            route_id=row.get("route_id"),
            from_street=row.get("from_street"),
            to_street=row.get("to_street"),
        )


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 100.0 else None


def _text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _date(value) -> date | None:
    """An ArcGIS date: milliseconds since 1970 (UTC) in GeoJSON, or ISO text."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, UTC).date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_feature(feature: Mapping, number: int, fiscal_year: int = FISCAL_YEAR) -> list[Block]:
    """The blocks of one GeoJSON feature as the layer serves it, or none.

    None where there is no PCI between 0 and 100 or no line. A MultiLineString
    gives one block a part, each with the feature's reading.
    """
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    pci = _number(properties.get("PCI"))
    if pci is None:
        return []
    if geometry.get("type") == "LineString":
        lines = [geometry.get("coordinates") or []]
    elif geometry.get("type") == "MultiLineString":
        lines = geometry.get("coordinates") or []
    else:
        return []
    surveyed = _date(properties.get("DATE1")) or fiscal_year_end(fiscal_year)
    object_id = properties.get("OBJECTID", feature.get("id", number))
    blocks = []
    for part, line in enumerate(lines):
        coordinates = [(float(c[0]), float(c[1])) for c in line if len(c) >= 2]
        if len(coordinates) < 2:
            continue
        blocks.append(
            Block(
                feature_id=f"{AGENCY}-fy{fiscal_year % 100:02d}-{object_id}-{part}",
                coordinates=coordinates,
                pci=pci,
                name=_text(properties.get("ROUTENAME")),
                surveyed=surveyed,
                category=_text(properties.get("PCICTEGORY")),
                route_id=_text(properties.get("ROUTEID")),
                from_street=_text(properties.get("FROMSTREET")),
                to_street=_text(properties.get("TOSTREET")),
            )
        )
    return blocks


def parse_layer(collection: Mapping, fiscal_year: int = FISCAL_YEAR) -> list[Block]:
    """Every block of a FeatureCollection as `scripts/fetch_agency_layer.py` stored it."""
    blocks: list[Block] = []
    for number, feature in enumerate(collection.get("features") or []):
        blocks.extend(parse_feature(feature, number, fiscal_year))
    return blocks


@dataclass(frozen=True)
class Override:
    """An approved RouteMaker correction to a street's reading."""

    osm_way_id: int
    reading: str  # KEEP_OSM, or one of BANDS
    reason: str


def load_overrides(path: Path = OVERRIDES) -> dict[int, Override]:
    """The checked-in corrections by way id; refused when a row is malformed,
    because a correction that silently fails to apply is not one."""
    if not path.exists():
        return {}
    rows = json.loads(path.read_text())
    found: dict[int, Override] = {}
    for row in rows.get("rows", []):
        reading = row["reading"]
        if reading != KEEP_OSM and reading not in BANDS:
            raise ValueError(f"{path}: way {row['osm_way_id']}: unknown reading {reading!r}")
        if not str(row.get("reason", "")).strip():
            raise ValueError(f"{path}: way {row['osm_way_id']}: a correction needs its reason")
        found[int(row["osm_way_id"])] = Override(int(row["osm_way_id"]), reading, row["reason"])
    return found


@dataclass(frozen=True)
class Reading:
    """What the rebuild does with one way the layer reached, and why."""

    osm_way_id: int
    pci: float
    surveyed: date
    blocks: tuple[str, ...]
    # The band the graph is given, or None where OSM's reading stands.
    applied: str | None
    # "pci", "override", "osm_newer", "not_street", "unpaved"
    why: str


def is_street(tags: Mapping[str, str]) -> bool:
    return tags.get("highway") in STREET_HIGHWAYS


def resolve(
    osm_way_id: int,
    tags: Mapping[str, str],
    shares: Iterable[tuple[Block, float]],
    edited: datetime | None = None,
    override: Override | None = None,
) -> Reading | None:
    """The reading for one way from the blocks it lies along (each with the
    share of the way it covers), or None where it lies along none.

    The way's PCI is the share-weighted mean of its blocks', and its survey the
    latest of theirs (the newest reading of any part of it).
    """
    pairs = [(block, share) for block, share in shares if share > 0]
    if not pairs:
        return None
    total = sum(share for _, share in pairs)
    pci = round(sum(block.pci * share for block, share in pairs) / total, 1)
    surveyed = max(block.surveyed for block, _ in pairs)
    ids = tuple(block.feature_id for block, _ in pairs)

    def reading(applied: str | None, why: str) -> Reading:
        return Reading(osm_way_id, pci, surveyed, ids, applied, why)

    if not is_street(tags):
        return reading(None, "not_street")
    if tags.get("surface") in UNPAVED_SURFACES:
        return reading(None, "unpaved")
    if override is not None:
        return reading(None if override.reading == KEEP_OSM else override.reading, "override")
    if tags.get("smoothness") and edited is not None and edited.date() > surveyed:
        return reading(None, "osm_newer")
    return reading(band(pci), "pci")


REPORT_HEADER = "osm_way_id,pci,band_applied,why,surveyed,blocks"


def report_csv(readings: Iterable[Reading]) -> str:
    """One line a way the layer reached, for the rebuild's reports folder."""
    lines = [REPORT_HEADER]
    for item in sorted(readings, key=lambda r: r.osm_way_id):
        lines.append(
            f"{item.osm_way_id},{item.pci},{item.applied or ''},{item.why},"
            f"{item.surveyed.isoformat()},{' '.join(item.blocks)}"
        )
    return "\n".join(lines) + "\n"
