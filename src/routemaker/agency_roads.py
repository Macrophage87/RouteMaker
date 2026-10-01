"""Road facts from an agency's own block layer, and what they say to the classifier.

OpenStreetMap is a volunteer's tagging of what is on the ground; a city's street
database is the city's record of what it signed, striped and counted. Where both
describe one road the agency's record is the better witness for a short list of
things - the posted speed, the lanes each way, whether the street is one-way,
the bike lane's type and width, parking and the daily count - and the owner
decided as much (OWNER-DECISIONS 151, 159): a matched agency value takes
precedence over the OSM tag and over this project's defaults, which stay the
fallback where nothing matched.

Three steps, kept apart so each can be tested alone:

* **parse** one layer's properties into `RoadFacts` (`parse_dc_roadway_block`,
  `parse_baltimore_centerline`): units, codes and the layer's quirks settled once
  and recorded as plain numbers per direction;
* **aggregate** the blocks a way was matched to (`pipeline.conflation.conflate_blocks`
  decides which and how much of the way each covers) into one `WayFacts`. OSM ways
  and agency blocks do not break at the same places, so a way can lie along
  several blocks, and the facts that describe it are the most stressful of
  theirs - the highest speed, the most lanes, the weakest facility - never an
  average that no block has;
* **overlay** the result onto the way's tags as the classifier reads them
  (`overlay`), saying for each attribute where its value came from.

The overlay changes what the classifier reads and not the tags written to the
graph, the same arrangement as `speed_corrections`: it is a statement about the
rider's stress, and what Valhalla does with a car's speed is a separate matter.

Layer quirks found on the data (retrieved 2026-10-01), because a parser that
trusts the field names reads them wrongly:

* DC's `SPEEDLIMITS_IB` is empty on all 13,833 blocks and `SPEEDLIMITS_OB` carries
  the block's limit. Each direction is kept as published and the way's speed is
  the highest present, so the day DDOT fills the inbound field it is read.
* DC's bike-lane, parking and travel-lane widths are totals over the block's
  lanes, in feet (two bike lanes of five feet are `10`); they are divided by the
  count here. The `BIKELANE_*` fields hold the direction the facility serves,
  `IB`, `OB` or `BD`.
* DC's inbound and outbound are not compass or digitising directions, so a
  one-way block says only that it is one-way (`SUMMARYDIRECTION` `IB` or `OB`).
* Baltimore's `fr_speed_limit` and `to_speed_limit` are filled on 19 of 48,522
  centerlines, all zero; its `speed` attribute is the number the city keeps on
  the line (25 on 26,722 of them, `1` on its alleys), and is read as the speed
  limit with that source named, so a reviewer sees that it is the city's field
  and not a posted-sign survey.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

METRES_PER_FOOT = 0.3048

DC_AGENCY = "dc-roadway-block"
BALTIMORE_AGENCY = "baltimore-centerline"
# The layers that record bike facilities on the street itself.
BIKE_AGENCIES = frozenset({DC_AGENCY})

# A posted limit below this is not a speed limit: DC has blocks at 0 and 5 mph,
# Baltimore's alleys are `1`. Read as "no value", so the way falls back to OSM
# and then to the default.
MIN_POSTED_MPH = 10
MAX_POSTED_MPH = 80

# What kind of bike facility a direction has, weakest first. The numbers are
# the rank `aggregate` takes a minimum over.
BIKE_NONE, BIKE_LANE, BIKE_BUFFERED, BIKE_PROTECTED = 0, 1, 2, 3

DIRECTIONS = ("ib", "ob")

# Ways of these classes take a street block only where the street name agrees: a
# service road or a track runs beside a street without being it.
NAME_REQUIRED_HIGHWAYS = frozenset({"service", "track"})

# Ways of these classes are matched to a block whatever the two names say:
# agencies and OSM name freeways, bridges and parkways differently (OSM's
# "Anacostia Freeway" is DC's "INTERSTATE 295"), and there is no street beside one
# for it to be mistaken for. Every other class is vetoed by a block that names
# a different street (`conflate_blocks(name_vetoed=...)`).
NAME_FREE_HIGHWAYS = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
    }
)


@dataclass(frozen=True)
class RoadFacts:
    """What one agency block says about its stretch of road.

    Per-direction values keep the layer's own labels as dict keys (`ib`/`ob` for
    DC), because which of them is which way along an OSM way is not recorded
    and is not needed: the classifier scores a way on the worse of its two
    directions. Everything is optional; an agency that does not publish a
    field simply leaves it out and the way keeps OSM's value.
    """

    agency: str
    name: str | None = None
    # Posted speed by direction label, mph.
    speed_mph: dict[str, int] = field(default_factory=dict)
    # Through lanes by direction label, plus the shared centre lane if any.
    lanes: dict[str, int] = field(default_factory=dict)
    # "one" or "both"; None where the layer does not say.
    way: str | None = None
    # Bike facility rank by direction label (BIKE_LANE, BIKE_BUFFERED, BIKE_PROTECTED).
    bike: dict[str, int] = field(default_factory=dict)
    contraflow: bool = False
    bike_width_ft: float | None = None
    parking_lanes: int | None = None
    parking_width_ft: float | None = None
    lane_width_ft: float | None = None
    aadt: int | None = None
    aadt_year: int | None = None
    pci_score: int | None = None
    functional_class: str | None = None
    alley: bool = False

    def to_json(self) -> dict:
        """Only what is present, so a block with little to say costs little."""
        out = {}
        for key, value in asdict(self).items():
            # Identity, not membership:  is true, and a block with
            # no parking lanes is saying so.
            if (value is None or value is False or value == {} or value == "") and (
                key != "agency"
            ):
                continue
            out[key] = value
        return out

    @classmethod
    def from_json(cls, row: Mapping) -> RoadFacts:
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in row.items() if key in known})


# -- parsing ----------------------------------------------------------------------


def _int(value) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _posted(value) -> int | None:
    number = _int(value)
    if number is None or not MIN_POSTED_MPH <= number <= MAX_POSTED_MPH:
        return None
    return number


def _per_lane(total, count) -> float | None:
    total, count = _float(total), _int(count)
    if total is None or not count or total <= 0:
        return None
    return round(total / count, 2)


DC_BIKE_FLAGS = (
    ("BIKELANE_PROTECTED", BIKE_PROTECTED),
    ("BIKELANE_DUAL_PROTECTED", BIKE_PROTECTED),
    ("BIKELANE_BUFFERED", BIKE_BUFFERED),
    ("BIKELANE_DUAL_BUFFERED", BIKE_BUFFERED),
    ("BIKELANE_CONVENTIONAL", BIKE_LANE),
)


def _dc_bike(properties: Mapping) -> dict[str, int]:
    """Bike facility rank in each direction, from the `BIKELANE_*` flags.

    A flag's value is the direction it serves. A dual (two-way) facility serves
    both whichever side the flag names. The best rank in each direction wins:
    a block with a conventional lane both ways and a protected one inbound has
    a protected facility inbound and a lane outbound.
    """
    ranks = {direction: BIKE_NONE for direction in DIRECTIONS}
    for flag, rank in DC_BIKE_FLAGS:
        value = properties.get(flag)
        if not value:
            continue
        value = str(value).strip().upper()
        if flag.startswith("BIKELANE_DUAL") or value == "BD":
            served = DIRECTIONS
        elif value == "IB":
            served = ("ib",)
        elif value == "OB":
            served = ("ob",)
        else:
            continue
        for direction in served:
            ranks[direction] = max(ranks[direction], rank)
    return {direction: rank for direction, rank in ranks.items() if rank}


def dc_street_name(properties: Mapping) -> str | None:
    return properties.get("ROUTENAME") or None


def parse_dc_roadway_block(properties: Mapping) -> RoadFacts:
    """One DC "Roadway Block" record (DDOT, MapServer layer 163) as `RoadFacts`."""
    speeds = {}
    for label, field_name in (("ib", "SPEEDLIMITS_IB"), ("ob", "SPEEDLIMITS_OB")):
        if (speed := _posted(properties.get(field_name))) is not None:
            speeds[label] = speed

    lanes = {}
    for label, field_name in (
        ("ib", "TOTALTRAVELLANESINBOUND"),
        ("ob", "TOTALTRAVELLANESOUTBOUND"),
        ("bidirectional", "TOTALTRAVELLANESBIDIRECTIONAL"),
        ("reversible", "TOTALTRAVELLANESREVERSIBLE"),
    ):
        if (count := _int(properties.get(field_name))) is not None:
            lanes[label] = count
    counted = sum(lanes.get(label, 0) for label in ("ib", "ob", "bidirectional", "reversible"))
    if counted == 0:
        # A block whose directions are all zero is one whose lanes are not
        # recorded (599 two-way blocks read 0 and 0), not a road with none. Where
        # the total is there without a direction (nine blocks) it is kept as the
        # whole street's, as Baltimore's `lane_count` is.
        total = _int(properties.get("TOTALTRAVELLANES"))
        lanes = {"total": total} if total and total > 0 else {}
    # Lanes are only kept where something is non-zero, so a block with a
    # reversible lane and nothing else still has them.
    lanes = {label: count for label, count in lanes.items() if count or label in ("ib", "ob")}

    summary = (properties.get("SUMMARYDIRECTION") or "").strip().upper()
    way = {"BD": "both", "IB": "one", "OB": "one"}.get(summary)

    bike = _dc_bike(properties)
    parking = _int(properties.get("TOTALPARKINGLANES"))
    return RoadFacts(
        agency=DC_AGENCY,
        name=dc_street_name(properties),
        speed_mph=speeds,
        lanes=lanes,
        way=way,
        bike=bike,
        contraflow=bool(properties.get("BIKELANE_CONTRAFLOW")),
        bike_width_ft=(
            _per_lane(properties.get("TOTALBIKELANEWIDTH"), properties.get("TOTALBIKELANES"))
            if bike
            else None
        ),
        parking_lanes=parking,
        parking_width_ft=_per_lane(properties.get("TOTALPARKINGLANEWIDTH"), parking),
        lane_width_ft=_per_lane(
            properties.get("TOTALTRAVELLANEWIDTH"), properties.get("TOTALTRAVELLANES")
        ),
        aadt=_int(properties.get("AADT")) or None,
        aadt_year=_int(properties.get("AADT_YEAR")),
        pci_score=_int(properties.get("PCI_SCORE")),
        functional_class=(
            str(properties["FHWAFUNCTIONALCLASS"])
            if properties.get("FHWAFUNCTIONALCLASS") is not None
            else None
        ),
    )


def baltimore_street_name(properties: Mapping) -> str | None:
    parts = [
        properties.get("dirpre"),
        properties.get("feanme"),
        properties.get("featype"),
        properties.get("dirsuf"),
    ]
    name = " ".join(str(part).strip() for part in parts if part and str(part).strip())
    return name or None


def parse_baltimore_centerline(properties: Mapping) -> RoadFacts | None:
    """One Baltimore "Street Centerline (Native)" record as `RoadFacts`.

    None for a record that is not a street a bicycle rides on the road: a line
    that is not active (`feat_status` other than `A`), and the layer's
    non-drivable features (`drivable` of `N`: footpaths, stairs and similar). An
    alley that is drivable keeps its facts and is flagged `alley`, and is given
    no speed.
    """
    if (properties.get("feat_status") or "A").strip() != "A":
        return None
    if properties.get("drivable") == "N":
        return None
    alley = properties.get("subtype") == "STRALY"

    speeds = {}
    for label, field_name in (("from", "fr_speed_limit"), ("to", "to_speed_limit")):
        if (speed := _posted(properties.get(field_name))) is not None:
            speeds[label] = speed
    if not speeds and not alley and (speed := _posted(properties.get("speed"))) is not None:
        # The city's `speed` attribute, not a surveyed sign; the label says so.
        speeds["centerline"] = speed

    direction = (properties.get("oneway") or "").strip().upper()
    lanes = {}
    if (count := _int(properties.get("lane_count"))) and count > 0:
        # `lane_count` is the whole street's; direction is not split.
        lanes["total"] = count
    return RoadFacts(
        agency=BALTIMORE_AGENCY,
        name=baltimore_street_name(properties),
        speed_mph=speeds,
        lanes=lanes,
        way="one" if direction in ("FT", "TF") else None,
        aadt=_int(properties.get("traffic_count_aadt")) or None,
        aadt_year=_int(properties.get("traffic_count_year")),
        functional_class=(properties.get("sha_class") or "").strip() or None,
        alley=alley,
    )


def iter_features(path: str | Path, chunk_bytes: int = 1 << 22) -> Iterator[dict]:
    """The features of a GeoJSON FeatureCollection one at a time.

    The Baltimore centerline is 152 MB of mostly-empty attribute columns, and
    `json.load` of it costs more memory than the build host has to spare, so
    this decodes one feature at a time from a sliding buffer.
    """
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    with open(path, encoding="utf-8") as handle:
        while True:
            data = handle.read(chunk_bytes)
            buffer += data
            if not started:
                at = buffer.find('"features"')
                at = buffer.find("[", at) if at >= 0 else -1
                if at < 0:
                    if not data:
                        return
                    continue
                buffer = buffer[at + 1 :]
                started = True
            while True:
                buffer = buffer.lstrip(" \n\r\t,")
                if not buffer:
                    break
                try:
                    feature, end = decoder.raw_decode(buffer)
                except ValueError:
                    break  # the feature continues in the next chunk
                yield feature
                buffer = buffer[end:]
            if not data:
                return


# -- names -------------------------------------------------------------------------

_SUFFIXES = {
    "st": "street",
    "ave": "avenue",
    "av": "avenue",
    "rd": "road",
    "blvd": "boulevard",
    "dr": "drive",
    "pl": "place",
    "ct": "court",
    "ln": "lane",
    "pkwy": "parkway",
    "hwy": "highway",
    "ter": "terrace",
    "cir": "circle",
    "fwy": "freeway",
    "sq": "square",
    "pk": "pike",
    "tpke": "turnpike",
    "xing": "crossing",
    # Not street types, but the same kind of abbreviation: Martin Luther King Jr
    # Avenue is "Junior" to OSM.
    "jr": "junior",
    "sr": "senior",
}
_DIRECTION_WORDS = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "nw": "northwest",
    "ne": "northeast",
    "sw": "southwest",
    "se": "southeast",
}
_GENERIC = (
    frozenset(_SUFFIXES.values())
    | frozenset(_DIRECTION_WORDS.values())
    | {"way", "bend", "pike", "turnpike"}
)


@functools.lru_cache(maxsize=65536)
def name_tokens(name: str | None) -> frozenset[str]:
    """The words of a street name that identify it: abbreviations expanded,
    punctuation dropped, and the street type and the quadrant left out, because
    OSM writes "4th Street Northeast" where the agency writes "4TH ST NE" and
    either may omit the quadrant."""
    if not name:
        return frozenset()
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    expanded = [_SUFFIXES.get(word, _DIRECTION_WORDS.get(word, word)) for word in words]
    return frozenset(word for word in expanded if word not in _GENERIC)


def names_agree(a: str | None, b: str | None) -> bool | None:
    """Whether two street names are the same street; None when either has no name.

    The identifying words of one are all in the other, so "Connecticut Avenue
    Northwest" agrees with "CONNECTICUT AVE NW" and with "Connecticut Avenue",
    and "K Street" does not agree with "L Street".
    """
    left, right = name_tokens(a), name_tokens(b)
    if not left or not right:
        return None
    return left <= right or right <= left


# -- aggregating the blocks a way lies along ---------------------------------------


@dataclass(frozen=True)
class WayFacts:
    """What the blocks along one OSM way say, taken together.

    Always the more stressful reading where blocks differ: the one tier a way
    carries is scored on its worst stretch, so the highest speed, the most lanes
    and the weakest facility describe it, and the value is never one no block
    has.
    """

    agency: str
    blocks: tuple[str, ...]
    speed_mph: int | None = None
    speed_by_direction: dict[str, int] = field(default_factory=dict)
    lanes_per_direction: int | None = None
    lanes_by_direction: dict[str, int] = field(default_factory=dict)
    # True when every block that says so is one-way, False when any is two-way.
    one_way: bool | None = None
    bike: dict[str, int] = field(default_factory=dict)
    contraflow: bool = False
    bike_width_ft: float | None = None
    parking_lanes: int | None = None
    parking_width_ft: float | None = None
    aadt: int | None = None
    aadt_year: int | None = None
    names_agree: bool | None = None


def lanes_per_direction(facts: RoadFacts) -> int | None:
    """The through lanes a rider meets in one direction on a block, at the
    busiest time: the more of its two directions' lanes, plus the lanes that
    reverse (Connecticut Avenue's: one each way and two that serve whichever
    way is the peak is three lanes in the peak direction, not one). The shared
    centre turn lane is not a through lane. A block that gives only a total is
    half of it on a two-way street and all of it on a one-way."""
    lanes = facts.lanes
    if not lanes:
        return None
    directional = [count for label, count in lanes.items() if label in ("ib", "ob", "from", "to")]
    if directional and max(directional) > 0:
        return max(directional) + lanes.get("reversible", 0)
    if lanes.get("reversible"):
        return lanes["reversible"]
    total = lanes.get("total")
    if not total:
        return None
    return total if facts.way == "one" else max(1, total // 2)


def aggregate(blocks: list[tuple[str, RoadFacts]], names: bool | None = None) -> WayFacts:
    """`WayFacts` for a way from the (block id, facts) pairs lying along it."""
    if not blocks:
        raise ValueError("a way with no blocks has no facts")
    facts = [f for _, f in blocks]

    speeds: dict[str, int] = {}
    for f in facts:
        for label, mph in f.speed_mph.items():
            speeds[label] = max(speeds.get(label, 0), mph)

    lanes: dict[str, int] = {}
    for f in facts:
        for label, count in f.lanes.items():
            lanes[label] = max(lanes.get(label, 0), count)
    per_block = [lanes_per_direction(f) for f in facts]
    known = [count for count in per_block if count]
    per_direction = max(known) if known else None

    ways = {f.way for f in facts if f.way}
    one_way = None if not ways else ways == {"one"}

    # The weakest facility in each direction across the blocks; a block with no
    # facility in a direction counts as none there.
    bike = {}
    for direction in DIRECTIONS:
        ranks = [f.bike.get(direction, BIKE_NONE) for f in facts]
        if min(ranks) > BIKE_NONE:
            bike[direction] = min(ranks)
    widths = [f.bike_width_ft for f in facts if f.bike_width_ft]
    parking = [f.parking_lanes for f in facts if f.parking_lanes is not None]
    parking_widths = [f.parking_width_ft for f in facts if f.parking_width_ft]

    counted = [f for f in facts if f.aadt]
    busiest = max(counted, key=lambda f: f.aadt) if counted else None

    return WayFacts(
        agency=facts[0].agency,
        blocks=tuple(block for block, _ in blocks),
        speed_mph=max(speeds.values()) if speeds else None,
        speed_by_direction=speeds,
        lanes_per_direction=per_direction,
        lanes_by_direction=lanes,
        one_way=one_way,
        bike=bike,
        contraflow=all(f.contraflow for f in facts),
        bike_width_ft=min(widths) if widths else None,
        parking_lanes=max(parking) if parking else None,
        parking_width_ft=max(parking_widths) if parking_widths else None,
        aadt=busiest.aadt if busiest else None,
        aadt_year=busiest.aadt_year if busiest else None,
        names_agree=names,
    )


# -- the overlay -------------------------------------------------------------------

SOURCE_OSM = "osm"
SOURCE_DEFAULT = "default"

_CYCLEWAY_PREFIX = "cycleway"
_PARKING_PREFIXES = ("parking:lane", "parking:left", "parking:right", "parking:both")
_FACILITY_VALUES = ("lane", "track", "opposite_lane", "opposite_track", "buffered_lane")


@dataclass(frozen=True)
class Overlay:
    tags: dict[str, str]
    # Attribute -> where the value the classifier reads came from: the agency
    # where it took precedence, `osm` where the way's own tag stood, `default`
    # where neither said and the classifier assumes.
    sources: dict[str, str]
    # Where the agency and the way disagree and the way was left alone.
    disagreements: tuple[str, ...] = ()


def _oneway_tag(tags: Mapping[str, str]) -> bool:
    return tags.get("oneway") in ("yes", "1", "-1", "true")


def overlay(tags: Mapping[str, str], facts: WayFacts) -> Overlay:
    """The way's tags as the classifier should read them, given its blocks' facts.

    A layer that publishes no bike facility (the Baltimore centerline) has
    nothing to say about one, and the way's own tags stand.
    """
    allow_bike = facts.agency in BIKE_AGENCIES
    out = dict(tags)
    sources: dict[str, str] = {}
    disagreements: list[str] = []
    agency = facts.agency

    # -- one-way: an agency that says one-way where OSM does not is believed;
    # one that says two-way where OSM says one-way is not, because a divided
    # road's carriageways are one-way ways on a two-way block.
    osm_oneway = _oneway_tag(tags)
    if facts.one_way is True and not osm_oneway:
        out["oneway"] = "yes"
        sources["oneway"] = agency
    else:
        sources["oneway"] = SOURCE_OSM if "oneway" in tags else SOURCE_DEFAULT
        if facts.one_way is False and osm_oneway:
            disagreements.append("oneway: agency two-way, OSM one-way")
    one_way = _oneway_tag(out)

    # -- posted speed
    if facts.speed_mph is not None:
        out["maxspeed"] = f"{facts.speed_mph} mph"
        sources["maxspeed"] = agency
    else:
        sources["maxspeed"] = SOURCE_OSM if tags.get("maxspeed") else SOURCE_DEFAULT

    # -- lanes in each direction. The classifier reads the larger of
    # `lanes:forward` and `lanes:backward` where either is present, and `lanes`
    # (halved on a two-way road) otherwise.
    if facts.lanes_per_direction:
        per = facts.lanes_per_direction
        for key in ("lanes", "lanes:forward", "lanes:backward"):
            out.pop(key, None)
        if one_way:
            out["lanes"] = str(per)
        else:
            out["lanes:forward"] = str(per)
            out["lanes:backward"] = str(per)
        sources["lanes"] = agency
    else:
        has_lanes = any(key in tags for key in ("lanes", "lanes:forward", "lanes:backward"))
        sources["lanes"] = SOURCE_OSM if has_lanes else SOURCE_DEFAULT

    # -- bike facility, only where the agency has one to give: its absence is
    # not evidence the OSM lane is gone (a lane painted since the layer was
    # cut), and where the two disagree the report says so.
    if allow_bike and (facts.bike or facts.contraflow):
        for key in [k for k in out if k.startswith(_CYCLEWAY_PREFIX)]:
            del out[key]
        width_m = round(facts.bike_width_ft * METRES_PER_FOOT, 2) if facts.bike_width_ft else None
        if len(facts.bike) == len(DIRECTIONS):
            rank, side = min(facts.bike.values()), "both"
        elif facts.bike:
            rank, side = next(iter(facts.bike.values())), "right"
        else:
            rank, side = None, None
        if rank:
            out[f"cycleway:{side}"] = "track" if rank == BIKE_PROTECTED else "lane"
            if rank == BIKE_BUFFERED:
                out[f"cycleway:{side}:buffer"] = "yes"
            if width_m and rank != BIKE_PROTECTED:
                out[f"cycleway:{side}:width"] = str(width_m)
        if facts.contraflow and side != "both":
            out["cycleway:left"] = "opposite_lane"
        sources["bike"] = agency
    elif allow_bike:
        has_osm = any(k.startswith(_CYCLEWAY_PREFIX) for k in tags)
        sources["bike"] = SOURCE_OSM if has_osm else SOURCE_DEFAULT
        if any(
            value in _FACILITY_VALUES
            for key, value in tags.items()
            if key.startswith(_CYCLEWAY_PREFIX) and not key.endswith((":width", ":buffer"))
        ):
            disagreements.append("bike facility: OSM has one, the agency records none")

    # -- parking
    if facts.parking_lanes is not None:
        for key in [k for k in out if k.startswith(_PARKING_PREFIXES)]:
            del out[key]
        if facts.parking_lanes == 0:
            out["parking:both"] = "no"
        elif facts.parking_lanes == 1:
            out["parking:right"] = "parallel"
            out["parking:left"] = "no"
        else:
            out["parking:both"] = "parallel"
        sources["parking"] = agency
    else:
        has_parking = any(k.startswith(_PARKING_PREFIXES) for k in tags)
        sources["parking"] = SOURCE_OSM if has_parking else SOURCE_DEFAULT

    sources["aadt"] = agency if facts.aadt else "none"
    return Overlay(out, sources, tuple(disagreements))
