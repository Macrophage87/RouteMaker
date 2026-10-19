"""Agency traffic signal lists, carried to the router's signal flag.

OSM in the District misses signals: a junction with a signal on the street and
nothing on the map reads "no signal mapped" in the junction model
(`core.junctions`), is priced as an unsignalised crossing of the busier road and
gets the ride cue "no signal mapped (Higher stress junction)". DDOT publishes
every signal it runs (DDOT Traffic Signals, DC GIS; docs/SOURCES.md), and DC data
beats OSM for the same fact (the owner, 2026-10-11), so the rebuild reads the list
and marks the junction node at each signal OSM does not have. MDOT SHA (every
Maryland signal but Baltimore City's), VDOT (Virginia's, a 2023 snapshot), Arlington
and Alexandria publish lists too
(`LICENCE_CONFIRMED` says which are read).

The installed file, `<reference>/signals.json`, is one row per signal,
`{"id", "source", "lon", "lat", "kind"}` (`kind` "signal", or "hawk" for a
pedestrian hybrid beacon), written by `scripts/install_reference_data.py
--dc-signals / --md-signals / --va-signals / --arlington-signals / --alexandria-signals /
--alexandria-hawks` from each layer as `scripts/fetch_agency_layer.py` stored it.
Optional: without it the map keeps OSM's signals only, and the load logs that it
is absent.

Matching, per signal:

- A signal OSM already has is left alone: an OSM node within `OSM_SIGNAL_M` that
  says signal (`highway=traffic_signals`, or a crossing node tagged with one).
  OSM often puts it on the stop lines 7-30 m before the junction node, which the
  junction model reads up each arm for the same distance (`APPROACH_M`). An OSM
  signal whose nearest junction is another junction, one the agency point does not
  reach, is that junction's (a diagonal avenue's junctions 20-30 m apart) and does
  not count.
- Otherwise every road junction node within `JUNCTION_M` is marked: a node where
  three or more road arms meet (two ways crossing, or one ending on another), not
  counting alleys, parking aisles and driveways, so a junction that is only an
  alley mouth beside the signal is not taken for it. A divided road's junction is
  two to four nodes 10-15 m apart around the point, so all of them.
- A HAWK stands at a mid-block crosswalk, not a junction, so it marks the nearest
  node where a crossing way meets a road within `JUNCTION_M` instead.
- No node in reach: the signal is counted as unmatched (beyond the extract, or
  the street is mapped differently) and nothing is marked.

The mark is `NODE_TAG`, which the transform turns into `highway=traffic_signals`
(lua/routemaker_remap.lua, `derives_signal`) over what the node itself says, since
DC data beats OSM: an `uncontrolled` or `unmarked` crosswalk (a HAWK's, as OSM often
still tags it) and a stop or give-way sign mapped on the junction become the
signal. A crossing whose `bicycle=no` upstream reopens keeps its class.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import signals

logger = logging.getLogger(__name__)

FILE_NAME = "signals.json"
# The derived node tag, in the `rm:` namespace lua/graph.lua strips; its own, not
# `signals.NODE_TAG`, because the transform reads the two marks differently.
NODE_TAG = "rm:agency_signal"
KINDS = frozenset({"signal", "hawk"})
# Each source, and whether its licence is confirmed. A source whose licence is not
# confirmed may be installed but is not read: the load logs it and the map keeps
# OSM's signals there (as `routemaker.pavement.LICENCE_CONFIRMED` does for DC-PCI).
# docs/SOURCES.md has each one's terms.
LICENCE_CONFIRMED = {
    # DDOT Traffic Signals: CC BY 4.0 (the item's licence, 2026-10-19).
    "ddot": True,
    # City of Alexandria OpenData portal: CC0 (Alex311, 2026-10-16).
    "alexandria": True,
    # MDOT SHA Traffic Signals: Maryland iMAP's terms, as for MDOT SHA's other layers
    # (same publisher, the same empty licence field; the owner, 2026-10-19).
    "mdot-sha": True,
    # Arlington County: "Please review the Arlington County data disclaimer"; the
    # county's terms are pending (docs/SOURCES.md, Bike Comfort Index).
    "arlington": False,
    # VDOT HMMS Traffic Signals (2023 Snapshot), Virginia Roads: the portal's VDOT
    # disclaimer only, as VDOT's traffic volume already read (the owner sent it,
    # 2026-10-19).
    "vdot": True,
}
SOURCES = frozenset(LICENCE_CONFIRMED)

# Metres. JUNCTION_M covers a divided road's junction nodes around DDOT's point (on
# the District's route centreline) without reaching the next junction on an
# ordinary block; OSM_SIGNAL_M is the junction model's approach walk
# (`routemaker.trace_junctions.APPROACH_M`), the reach in which it already reads an
# OSM signal as this junction's.
JUNCTION_M = 20.0
OSM_SIGNAL_M = 30.0

# Service roads that never make a signalised junction on their own. A signalised
# entrance (a plain `service` road) still counts.
MINOR_SERVICE = frozenset({"alley", "parking_aisle", "driveway", "drive-through"})

# DDOT's STATUS values (and the like in other agencies' lists) that say a signal is
# not running. Read as words, lower-cased; anything else is taken as in service.
NOT_IN_SERVICE = ("remov", "propos", "plan", "design", "construct", "abandon", "inactive",
                  "retired", "future")  # fmt: skip

EARTH_M = 6_371_000.0


class SignalListInvalid(ValueError):
    """The installed file has a row the rebuild cannot read."""


@dataclass(frozen=True)
class Signal:
    feature_id: str
    source: str
    lon: float
    lat: float
    kind: str = "signal"

    def to_json(self) -> dict:
        return {
            "id": self.feature_id,
            "source": self.source,
            "lon": round(self.lon, 7),
            "lat": round(self.lat, 7),
            "kind": self.kind,
        }


def in_service(status: object) -> bool:
    if status is None:
        return True
    text = str(status).strip().lower()
    return not any(word in text for word in NOT_IN_SERVICE)


def _yes(value: object) -> bool:
    return str(value or "").strip().lower() in {"yes", "y", "true", "1"}


def _rows(
    doc: Mapping,
    source: str,
    *,
    keep=lambda props: (True, ""),
    kind=lambda props: "signal",
    id_fields: Sequence[str] = ("GLOBALID", "OBJECTID"),
    id_prefix: str | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """A layer (GeoJSON as fetched) as installed rows, and how many records each
    reason left out. `keep` says whether a record is a running signal (and why
    not); `kind` names a HAWK. Field names are read in upper case whatever case the
    layer gives them (a hosted layer's `objectid`, `GlobalID`). Each id is
    `<id_prefix>:<the first id field with a value>`, the prefix the source unless
    given: two layers of one source number their records from 1 alike."""
    rows: list[dict] = []
    dropped: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    for feature in doc.get("features", []):
        props = {str(k).upper(): v for k, v in (feature.get("properties") or {}).items()}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point" or not geometry.get("coordinates"):
            dropped["no point"] += 1
            continue
        kept, reason = keep(props)
        if not kept:
            dropped[reason] += 1
            continue
        key = next((props[f] for f in id_fields if props.get(f) not in (None, "")), None)
        feature_id = f"{id_prefix or source}:{key}"
        if key is None or feature_id in seen:
            dropped["no id or a repeated id"] += 1
            continue
        seen.add(feature_id)
        lon, lat = geometry["coordinates"][:2]
        rows.append(Signal(feature_id, source, float(lon), float(lat), kind(props)).to_json())
    return rows, dict(dropped)


def _status(props: Mapping, field_name: str) -> tuple[bool, str]:
    value = props.get(field_name)
    return (True, "") if in_service(value) else (False, f"{field_name} {value}")


def ddot_rows(doc: Mapping) -> tuple[list[dict], dict[str, int]]:
    """DDOT Traffic Signals: every record whose `STATUS` says it runs; `HAWK` yes is
    a HAWK."""
    return _rows(
        doc,
        "ddot",
        keep=lambda props: _status(props, "STATUS"),
        kind=lambda props: "hawk" if _yes(props.get("HAWK")) else "signal",
    )


# MDOT SHA's traffic control device type for a traffic control signal. The layer
# also lists beacons, pre-emption gear, detectors and signs, none of them a signal.
MDOT_SIGNAL_TYPE = "1"


def mdot_sha_rows(doc: Mapping) -> tuple[list[dict], dict[str, int]]:
    """MDOT SHA Traffic Signals: traffic control signals (`TCD_Type` 1) that are
    not `Proposed` (`OWNER_DESC`). It covers county and city signals as well as the
    state's, except Baltimore City's."""

    def keep(props: Mapping) -> tuple[bool, str]:
        device = str(props.get("TCD_TYPE") or "").strip()
        if device != MDOT_SIGNAL_TYPE:
            return False, f"device type {device or 'none'}"
        return _status(props, "OWNER_DESC")

    return _rows(doc, "mdot-sha", keep=keep, id_fields=("SIGNAL_ID", "OBJECTID"))


def arlington_rows(doc: Mapping) -> tuple[list[dict], dict[str, int]]:
    """Arlington County's Intersection Points: `TrafficControlType` Signalized, not
    still in design or construction (`ActiveProjectStatus`), and not retired (any
    field named for retirement with a value)."""

    def keep(props: Mapping) -> tuple[bool, str]:
        control = str(props.get("TRAFFICCONTROLTYPE") or "")
        if control.strip().lower() != "signalized":
            return False, f"control {control or 'none'}"
        retired = [k for k, v in props.items() if "retire" in k.lower() and v not in (None, "")]
        if retired:
            return False, "retired"
        status = str(props.get("ACTIVEPROJECTSTATUS") or "").strip().lower()
        if status in {"design", "construction"}:
            return False, f"ActiveProjectStatus {props.get('ACTIVEPROJECTSTATUS')}"
        return True, ""

    return _rows(doc, "arlington", keep=keep)


def alexandria_rows(doc: Mapping, kind: str = "signal") -> tuple[list[dict], dict[str, int]]:
    """City of Alexandria Smart Mobility Data: the signalised intersections layer
    (every record a signal) or the HAWK layer (`kind` "hawk")."""
    return _rows(
        doc,
        "alexandria",
        kind=lambda props: kind,
        id_prefix="alexandria-hawk" if kind == "hawk" else None,
    )


def _vdot_kind(subtype: object) -> str | None:
    """VDOT's `ASSET_SUBTYPE` as a kind: a Pedestrian Hybrid Beacon is a HAWK, a
    Traffic Signal a signal, an Intersection Flasher neither. Read by its words, so
    the coded value's name ("1-Traffic Signal") and its description both read."""
    text = str(subtype or "").strip().lower()
    if "hybrid" in text or "beacon" in text:
        return "hawk"
    if "signal" in text and "flash" not in text:
        return "signal"
    return None


def vdot_rows(doc: Mapping) -> tuple[list[dict], dict[str, int]]:
    """VDOT HMMS Traffic Signals (2023 Snapshot): `ASSET_SUBTYPE` Traffic Signal
    or Pedestrian Hybrid Beacon (an Intersection Flasher is left out) whose
    `STATUS` is Active (code `Active`, name `3-Active`). Every Virginia signal VDOT
    kept in HMMS up to October 2023, Fairfax's and the other counties' included; the
    snapshot is not updated. A record whose subtype reads as neither is counted by
    its value, so a layer coded otherwise shows in the installer's output."""

    def keep(props: Mapping) -> tuple[bool, str]:
        if _vdot_kind(props.get("ASSET_SUBTYPE")) is None:
            return False, f"subtype {props.get('ASSET_SUBTYPE') or 'none'}"
        status = str(props.get("STATUS") or "").strip().lower()
        if "active" not in status:
            return False, f"STATUS {props.get('STATUS') or 'none'}"
        return True, ""

    return _rows(doc, "vdot", keep=keep, kind=lambda props: _vdot_kind(props["ASSET_SUBTYPE"]))


def load(path: Path) -> tuple[Signal, ...]:
    """The installed signals, or none (with a warning) where not installed."""
    if not path.exists():
        logger.warning(
            "%s is absent, so no agency signal list is read (DDOT, MDOT SHA, VDOT, "
            "Arlington, Alexandria): the map keeps OSM's signals only. Install it with "
            "scripts/install_reference_data.py --dc-signals (and the others' flags)",
            path,
        )
        return ()
    out = []
    unlicensed: dict[str, int] = defaultdict(int)
    for row in json.loads(path.read_text()):
        missing = [key for key in ("id", "source", "lon", "lat", "kind") if key not in row]
        if missing:
            raise SignalListInvalid(f"{path}: record {row.get('id')!r}: no {', '.join(missing)}")
        if row["source"] not in SOURCES:
            raise SignalListInvalid(f"{path}: record {row['id']}: unknown source {row['source']!r}")
        if row["kind"] not in KINDS:
            raise SignalListInvalid(f"{path}: record {row['id']}: unknown kind {row['kind']!r}")
        if not LICENCE_CONFIRMED[row["source"]]:
            unlicensed[row["source"]] += 1
            continue
        out.append(
            Signal(row["id"], row["source"], float(row["lon"]), float(row["lat"]), row["kind"])
        )
    for source, count in sorted(unlicensed.items()):
        logger.warning(
            "%s: %d %s signals installed but not read, their licence not yet confirmed "
            "(agency_signals.LICENCE_CONFIRMED; docs/SOURCES.md)",
            path,
            count,
            source,
        )
    return tuple(out)


def _counts_as_junction_arm(tags: Mapping[str, str]) -> bool:
    return signals.is_road(tags) and tags.get("service") not in MINOR_SERVICE


def near_nodes(ways: Iterable, agency: Sequence[Signal]) -> dict[int, tuple[float, float]]:
    """The located way nodes within about `JUNCTION_M` of an agency signal (by grid
    cell, so a little more), with their locations. Matching looks at these alone:
    the whole region's nodes would not fit in the rebuild's memory as a dict."""
    cell_deg = JUNCTION_M / 111_320.0

    def cell(lon: float, lat: float) -> tuple[int, int]:
        return (math.floor(lon / cell_deg), math.floor(lat / cell_deg))

    # A cell is JUNCTION_M north to south and about 0.78 of it east to west at the
    # region's latitude (38.5 to 39.5 N), so three cells each way reach past it.
    wanted: set[tuple[int, int]] = set()
    for signal in agency:
        cx, cy = cell(signal.lon, signal.lat)
        wanted.update((x, y) for x in range(cx - 3, cx + 4) for y in range(cy - 3, cy + 4))
    out: dict[int, tuple[float, float]] = {}
    for way in ways:
        for index, lon, lat in way.located_points():
            if cell(lon, lat) in wanted:
                out.setdefault(way.node_ids[index], (lon, lat))
    return out


def _arms(ways: Iterable, keep, only: Mapping[int, object]) -> dict[int, int]:
    """Each node in `only`'s number of arms on the ways `keep` takes: two where a way
    passes through it, one where a way ends there (a closed way's two ends, one node,
    make two)."""
    arms: dict[int, int] = defaultdict(int)
    for way in ways:
        if not keep(way.tags):
            continue
        nodes = way.node_ids
        last = len(nodes) - 1
        for index, node in enumerate(nodes):
            if node in only:
                arms[node] += 1 if index in (0, last) else 2
    return arms


def junction_nodes(
    ways: Sequence, located: Mapping[int, tuple[float, float]]
) -> dict[int, tuple[float, float]]:
    """Road junction nodes among `located`, with their locations: three or more
    road arms."""
    arms = _arms(ways, _counts_as_junction_arm, located)
    return {node: located[node] for node, count in arms.items() if count >= 3}


def crossing_nodes(
    ways: Sequence, located: Mapping[int, tuple[float, float]]
) -> dict[int, tuple[float, float]]:
    """Nodes among `located` where a crossing way meets a road, with their locations."""
    crossing = {
        node
        for way in ways
        if signals.is_crossing_way(way.tags)
        for node in way.node_ids
        if node in located
    }
    road = {
        node
        for way in ways
        if signals.is_road(way.tags)
        for node in way.node_ids
        if node in crossing
    }
    return {node: located[node] for node in road}


class _Grid:
    """Points bucketed by a cell of about `cell_m`, for "what is within r metres"."""

    def __init__(self, points: Mapping[int, tuple[float, float]], cell_m: float) -> None:
        self.cell_deg = cell_m / 111_320.0
        self.points = points
        self.cells: dict[tuple[int, int], list[int]] = defaultdict(list)
        for key, (lon, lat) in points.items():
            self.cells[self._cell(lon, lat)].append(key)

    def _cell(self, lon: float, lat: float) -> tuple[int, int]:
        return (math.floor(lon / self.cell_deg), math.floor(lat / self.cell_deg))

    def within(self, lon: float, lat: float, radius_m: float) -> list[tuple[float, int]]:
        """(distance, key) of every point within `radius_m`, nearest first."""
        cos_lat = math.cos(math.radians(lat))
        reach = math.ceil(radius_m / 111_320.0 / max(cos_lat, 0.1) / self.cell_deg)
        cx, cy = self._cell(lon, lat)
        found = []
        for x in range(cx - reach, cx + reach + 1):
            for y in range(cy - reach, cy + reach + 1):
                for key in self.cells.get((x, y), ()):
                    plon, plat = self.points[key]
                    distance = metres(lon, lat, plon, plat)
                    if distance <= radius_m:
                        found.append((distance, key))
        return sorted(found)


def metres(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Equirectangular distance; within a few hundred metres it is exact enough."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return EARTH_M * math.hypot(x, y)


@dataclass
class Match:
    """What the list did to the map: the nodes to mark and a count of each outcome
    per source, for the log and the rebuild's report."""

    nodes: set[int] = field(default_factory=set)
    already_in_osm: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    added: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    unmatched: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # (signal id, lon, lat, outcome, marked node ids) per signal, for the report.
    rows: list[tuple[str, float, float, str, tuple[int, ...]]] = field(default_factory=list)


def match(
    agency: Sequence[Signal],
    ways: Sequence,
    osm_signals: Mapping[int, tuple[float, float]],
) -> Match:
    """Which junction nodes the agency signals mark (the module docstring's rules)."""
    result = Match()
    if not agency:
        return result
    located = near_nodes(ways, agency)
    junctions = _Grid(junction_nodes(ways, located), JUNCTION_M)
    crossings = _Grid(crossing_nodes(ways, located), JUNCTION_M)
    osm = _Grid(osm_signals, OSM_SIGNAL_M)
    for signal in agency:
        if signal.kind == "hawk":
            near = crossings.within(signal.lon, signal.lat, JUNCTION_M)[:1]
        else:
            near = junctions.within(signal.lon, signal.lat, JUNCTION_M)
        marked = tuple(node for _distance, node in near)
        if any(
            _osm_signal_is_ours(osm.points[key], marked, junctions)
            for _distance, key in osm.within(signal.lon, signal.lat, OSM_SIGNAL_M)
        ):
            result.already_in_osm[signal.source] += 1
            result.rows.append((signal.feature_id, signal.lon, signal.lat, "in OSM", ()))
            continue
        if not marked:
            result.unmatched[signal.source] += 1
            result.rows.append((signal.feature_id, signal.lon, signal.lat, "unmatched", ()))
            continue
        result.added[signal.source] += 1
        result.nodes.update(marked)
        result.rows.append((signal.feature_id, signal.lon, signal.lat, "added", marked))
    return result


def _osm_signal_is_ours(point: tuple[float, float], ours: tuple[int, ...], junctions) -> bool:
    """Whether an OSM signal near an agency point is that point's: its nearest
    junction node is one the point marks, or none is in the approach's reach of it
    (a stop line out on an arm), or the point marks none."""
    if not ours:
        return True
    nearest = junctions.within(point[0], point[1], OSM_SIGNAL_M)[:1]
    return not nearest or nearest[0][1] in ours


def node_tags(nodes: Iterable[int]) -> dict[int, dict[str, str]]:
    """The extract's node tags for the nodes `match` marks."""
    return {node: {NODE_TAG: "yes"} for node in nodes}


def is_osm_signal(tags: Mapping[str, str]) -> bool:
    """A node OSM already maps as a signal: `highway=traffic_signals`, or a crossing
    node tagged with one (`pipeline.signals.is_signalised`)."""
    if tags.get("highway") == "traffic_signals":
        return True
    return tags.get("highway") == "crossing" and signals.is_signalised(tags)


def bounds(agency: Sequence[Signal], margin_m: float = OSM_SIGNAL_M) -> tuple[float, ...]:
    """(west, south, east, north) around every agency signal, with a margin."""
    lons = [s.lon for s in agency]
    lats = [s.lat for s in agency]
    pad = margin_m / 111_320.0 * 2
    return (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)


def read_osm_signals(pbf: Path | str, box: tuple[float, ...]) -> dict[int, tuple[float, float]]:
    """The extract's signal nodes inside `box`, with their locations: one pass over
    the nodes that carry a `highway` tag."""
    import osmium

    west, south, east, north = box
    found: dict[int, tuple[float, float]] = {}
    processor = osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(
        osmium.filter.KeyFilter("highway")
    )
    for node in processor:
        lon, lat = node.location.lon, node.location.lat
        if not (west <= lon <= east and south <= lat <= north):
            continue
        if is_osm_signal({tag.k: tag.v for tag in node.tags}):
            found[node.id] = (lon, lat)
    return found


def summary(result: Match) -> str:
    sources = sorted(set(result.already_in_osm) | set(result.added) | set(result.unmatched))
    return (
        "; ".join(
            f"{source}: {result.added.get(source, 0)} added, "
            f"{result.already_in_osm.get(source, 0)} already in OSM, "
            f"{result.unmatched.get(source, 0)} with no junction in reach"
            for source in sources
        )
        or "no agency signals"
    )


def report_csv(result: Match) -> str:
    """One CSV row per agency signal: what the rebuild did with it."""
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["signal_id", "lon", "lat", "outcome", "marked_osm_nodes"])
    for feature_id, lon, lat, outcome, nodes in result.rows:
        writer.writerow([feature_id, lon, lat, outcome, " ".join(str(n) for n in nodes)])
    return out.getvalue()
