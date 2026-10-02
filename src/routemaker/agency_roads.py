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
* DC's outbound is the block's digitising direction and inbound is against it,
  as measured on the one-way blocks (review r1: `SUMMARYDIRECTION` `OB` runs
  with the line 1,023 times to 49, `IB` against it 888 to 33). The matcher says
  whether each OSM way runs with its block or against it (`BlockShare.along`),
  so a one-way carriageway of a divided road takes its own direction's lanes
  and bike lane, and a lane against a one-way's traffic is a contraflow lane.
* Baltimore's `fr_speed_limit` and `to_speed_limit` are filled on 19 of 48,522
  centerlines, all zero; its `speed` attribute is the number the city keeps on
  the line (25 on 26,722 of them, `1` on its alleys), and is read as the speed
  limit with that source named, so a reviewer sees that it is the city's field
  and not a posted-sign survey. It fills only where OSM has no `maxspeed`: OSM's
  posted speed wins (OWNER-DECISIONS 184, "Fill gaps only").

`functional_class` is parsed and stored but nothing reads it, deliberately.
Item 151 lists it among the Roadway Block's facts, but the Furth tables the
classifier applies take speed, lanes, volume and the facility, not a class. The
road class the classifier does read (for the speed defaults and the arterial
floor) is OSM's `highway`, which exists everywhere in the region, not only on
the matched streets. The class is kept for the reports and as a feature for the
decimal stress model (FOLLOWUP-DECIMAL-STRESS, item 156).
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
# agencies and OSM name freeways differently (OSM's "Anacostia Freeway" is DC's
# "INTERSTATE 295"), and there is no street beside one for it to be mistaken
# for. Every other class is vetoed by a block that names a different street
# (`conflate_blocks(name_free=...)`). Primary and secondary roads were in this
# set until review r1 found them taking a neighbour's or a cross street's block
# where no agreeing block was near (North Capitol Street took Clermont Drive's;
# Ohio Drive SW took East Basin Drive's 33,679 vehicles a day).
NAME_FREE_HIGHWAYS = frozenset({"motorway", "motorway_link", "trunk", "trunk_link"})

# The agencies whose posted speed only fills a gap in OSM's. Baltimore's `speed`
# field is the city's attribute, not a survey of signs, and the owner chose
# "Fill gaps only (Recommended)" (OWNER-DECISIONS 184). DC's posted limits take
# precedence over OSM's (item 151).
SPEED_FILLS_ONLY = frozenset({BALTIMORE_AGENCY})

# The directory the internal-comparison layers are kept in. Arlington's Bike
# Comfort Index and Alexandria's Transport Streets are for internal comparison
# only (OWNER-DECISIONS 153, 155) and are never a source: nothing that feeds the
# rebuild, a fixture or a published report reads from it (`refuse_internal_only`).
INTERNAL_ONLY_DIR = "internal-only"


class InternalOnlySource(ValueError):
    """An internal-comparison layer offered where a published input is read."""


def refuse_internal_only(path: str | Path) -> Path:
    """`path`, or `InternalOnlySource` when it lies under an `internal-only`
    directory."""
    if INTERNAL_ONLY_DIR in Path(path).parts or INTERNAL_ONLY_DIR in Path(path).resolve().parts:
        raise InternalOnlySource(
            f"{path} is under {INTERNAL_ONLY_DIR}/: internal comparison only "
            "(OWNER-DECISIONS 155), never a source for the rebuild or published output"
        )
    return Path(path)


def is_link(tags: Mapping[str, str]) -> bool:
    """A slip road (`*_link`). It keeps its own lanes and is given no block's
    count: review r1 found unnamed ramps taking the main road's block, and a
    one-lane ramp read as two to four lanes."""
    return str(tags.get("highway", "")).endswith("_link")


@dataclass(frozen=True)
class RoadFacts:
    """What one agency block says about its stretch of road.

    Per-direction values keep the layer's own labels as dict keys (`ib`/`ob` for
    DC); which of them runs which way along an OSM way is the matcher's to say
    (`aggregate`'s `along`), because a way can be digitised either way along its
    block. Everything is optional; an agency that does not publish a field
    simply leaves it out and the way keeps OSM's value.
    """

    agency: str
    name: str | None = None
    # Posted speed by direction label, mph.
    speed_mph: dict[str, int] = field(default_factory=dict)
    # Through lanes by direction label, plus the shared centre lane if any.
    lanes: dict[str, int] = field(default_factory=dict)
    # "one" or "both"; None where the layer does not say.
    way: str | None = None
    # On a one-way block, whether its traffic runs with the line's digitising
    # direction (DC `OB`, Baltimore `FT`) or against it (`IB`, `TF`).
    oneway_with: bool | None = None
    # Bike facility rank by direction label (BIKE_LANE, BIKE_BUFFERED, BIKE_PROTECTED).
    bike: dict[str, int] = field(default_factory=dict)
    contraflow: bool = False
    bike_width_ft: float | None = None
    # The direction labels whose bike lane runs beside a parking lane (DC's
    # `BIKELANE_PARKINGLANE_ADJACENT`): where Furth measures the lane's reach.
    bike_beside_parking: tuple[str, ...] = ()
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
            # Identity, not equality: `0 == False` is true, and a block with
            # no parking lanes is saying so.
            if (value is None or value is False or value in ({}, (), "")) and (key != "agency"):
                continue
            out[key] = list(value) if isinstance(value, tuple) else value
        return out

    @classmethod
    def from_json(cls, row: Mapping) -> RoadFacts:
        known = cls.__dataclass_fields__
        values = {key: value for key, value in row.items() if key in known}
        if "bike_beside_parking" in values:
            values["bike_beside_parking"] = tuple(values["bike_beside_parking"])
        return cls(**values)


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
    adjacent = (properties.get("BIKELANE_PARKINGLANE_ADJACENT") or "").strip().upper()
    beside_parking = {"BD": DIRECTIONS, "IB": ("ib",), "OB": ("ob",)}.get(adjacent, ())
    return RoadFacts(
        agency=DC_AGENCY,
        name=dc_street_name(properties),
        speed_mph=speeds,
        lanes=lanes,
        way=way,
        oneway_with={"OB": True, "IB": False}.get(summary),
        bike=bike,
        bike_beside_parking=tuple(d for d in beside_parking if d in bike),
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
        oneway_with={"FT": True, "TF": False}.get(direction),
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
# The words that end a street name as its type ("Street", "AVE"). A compass word
# just before one is the street's own name, not a quadrant: "E Street", "N ST
# NW", "W Place", Baltimore's "North Avenue".
_STREET_TYPES = (frozenset(_SUFFIXES) | frozenset(_SUFFIXES.values()) | {"way", "bend"}) - {
    "jr",
    "sr",
    "junior",
    "senior",
}


def _singular(word: str) -> str:
    """A plural street word made singular, so "East Meadow Court" and "EAST
    MEADOWS CT" are one street (review r1). Both names pass through it, so a
    name that only looks plural ("Adams") changes the same way on both sides."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


@functools.lru_cache(maxsize=65536)
def name_tokens(name: str | None) -> frozenset[str]:
    """The words of a street name that identify it: abbreviations expanded,
    punctuation dropped, plurals made singular, and the street type and the
    quadrant left out, because OSM writes "4th Street Northeast" where the
    agency writes "4TH ST NE" and either may omit the quadrant.

    A compass word directly followed by the street type is the street's name and
    is kept, so "E Street" and "N Street" are different streets (review r1: they
    had no identifying word at all, so neither agreed nor disagreed)."""
    if not name:
        return frozenset()
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    kept = []
    for number, word in enumerate(words):
        expanded = _SUFFIXES.get(word, _DIRECTION_WORDS.get(word, word))
        following = words[number + 1] if number + 1 < len(words) else None
        if word in _DIRECTION_WORDS or word in _DIRECTION_WORDS.values():
            if following in _STREET_TYPES:
                kept.append(expanded)
            continue
        if expanded not in _GENERIC:
            kept.append(_singular(expanded))
    return frozenset(kept)


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
    # The busiest direction's through lanes on any block, direction unknown.
    lanes_per_direction: int | None = None
    lanes_by_direction: dict[str, int] = field(default_factory=dict)
    # Through lanes in the way's own digitising direction and against it, where
    # the matcher knows which way the way runs along each block; None where it
    # does not or a block records no lanes for that direction.
    lanes_forward: int | None = None
    lanes_backward: int | None = None
    # True when every block that says so is one-way, False when any is two-way.
    one_way: bool | None = None
    # On an agency one-way, whether its traffic runs the way's digitising
    # direction (True) or against it (False); None where unknown or mixed.
    oneway_forward: bool | None = None
    bike: dict[str, int] = field(default_factory=dict)
    # The weakest facility rank in the way's own direction and against it, and
    # whether those are known (every block's direction along the way is).
    bike_forward: int = BIKE_NONE
    bike_backward: int = BIKE_NONE
    direction_known: bool = False
    contraflow: bool = False
    bike_width_ft: float | None = None
    parking_lanes: int | None = None
    parking_width_ft: float | None = None
    # Whether every painted lane on the way runs beside a parking lane by the
    # agency's own record (DC's `BIKELANE_PARKINGLANE_ADJACENT`).
    lane_beside_parking: bool = False
    aadt: int | None = None
    aadt_year: int | None = None
    names_agree: bool | None = None

    @property
    def parking_reach_m(self) -> float | None:
        """The parking lane's width, in metres, to add to a painted lane's for
        Furth's reach beside parking: only where the agency records the lane as
        beside a parking lane and gives the parking lane's width. None
        otherwise, and the lane is measured on its own, the narrower reading."""
        if not self.lane_beside_parking or not self.parking_width_ft:
            return None
        return self.parking_width_ft * METRES_PER_FOOT


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


def _labels(along: bool | None) -> tuple[str, str] | None:
    """The block's direction labels for the way's (forward, backward): DC's `OB`
    is the line's digitising direction, so a way running with the line goes
    outbound."""
    if along is None:
        return None
    return ("ob", "ib") if along else ("ib", "ob")


def _directional_lanes(facts: RoadFacts, label: str) -> int | None:
    """Through lanes one direction of a block has at its busiest: its own lanes
    plus the reversible ones. None where the block records none that way."""
    count = facts.lanes.get(label)
    if not count:
        return None
    return count + facts.lanes.get("reversible", 0)


def aggregate(
    blocks: list[tuple[str, RoadFacts]] | list[tuple[str, RoadFacts, bool | None]],
    names: bool | None = None,
) -> WayFacts:
    """`WayFacts` for a way from the (block id, facts[, along]) lying along it.

    `along` is whether the way runs with the block's digitising direction
    (`pipeline.conflation.BlockShare.along`); without it the directions are
    unknown and the way takes the busier one in both.
    """
    if not blocks:
        raise ValueError("a way with no blocks has no facts")
    facts = [entry[1] for entry in blocks]
    alongs = [entry[2] if len(entry) > 2 else None for entry in blocks]
    direction_known = all(along is not None for along in alongs)

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

    # Each direction of the way: the block's own count that way where the way's
    # direction along the block is known and the block records one, else the
    # block's busier direction (the more stressful reading).
    forward: list[int] = []
    backward: list[int] = []
    for f, along, fallback in zip(facts, alongs, per_block, strict=True):
        labels = _labels(along)
        ahead = _directional_lanes(f, labels[0]) if labels else None
        behind = _directional_lanes(f, labels[1]) if labels else None
        if ahead or fallback:
            forward.append(ahead or fallback)
        if behind or fallback:
            backward.append(behind or fallback)

    ways = {f.way for f in facts if f.way}
    one_way = None if not ways else ways == {"one"}
    flows = {
        f.oneway_with == along
        for f, along in zip(facts, alongs, strict=True)
        if f.way == "one" and f.oneway_with is not None and along is not None
    }
    oneway_forward = next(iter(flows)) if one_way and len(flows) == 1 else None

    # The weakest facility in each direction across the blocks; a block with no
    # facility in a direction counts as none there.
    bike = {}
    for direction in DIRECTIONS:
        ranks = [f.bike.get(direction, BIKE_NONE) for f in facts]
        if min(ranks) > BIKE_NONE:
            bike[direction] = min(ranks)
    bike_forward = bike_backward = BIKE_NONE
    if direction_known:
        bike_forward = min(
            f.bike.get(_labels(along)[0], BIKE_NONE) for f, along in zip(facts, alongs, strict=True)
        )
        bike_backward = min(
            f.bike.get(_labels(along)[1], BIKE_NONE) for f, along in zip(facts, alongs, strict=True)
        )
    widths = [f.bike_width_ft for f in facts if f.bike_width_ft]
    parking = [f.parking_lanes for f in facts if f.parking_lanes is not None]
    # The narrowest parking lane, as the narrowest bike lane: the reach a rider
    # has on the way is the worst block's (review r1: the widest let one 9 ft
    # block lift a way whose other four blocks were 8 ft).
    parking_widths = [f.parking_width_ft for f in facts if f.parking_width_ft]
    painted = (BIKE_LANE, BIKE_BUFFERED)
    lane_beside_parking = any(rank in painted for f in facts for rank in f.bike.values()) and all(
        set(f.bike_beside_parking) >= {d for d, rank in f.bike.items() if rank in painted}
        for f in facts
    )

    counted = [f for f in facts if f.aadt]
    busiest = max(counted, key=lambda f: f.aadt) if counted else None

    return WayFacts(
        agency=facts[0].agency,
        blocks=tuple(entry[0] for entry in blocks),
        speed_mph=max(speeds.values()) if speeds else None,
        speed_by_direction=speeds,
        lanes_per_direction=per_direction,
        lanes_by_direction=lanes,
        lanes_forward=max(forward) if direction_known and forward else None,
        lanes_backward=max(backward) if direction_known and backward else None,
        one_way=one_way,
        oneway_forward=oneway_forward,
        bike=bike,
        bike_forward=bike_forward,
        bike_backward=bike_backward,
        direction_known=direction_known,
        contraflow=all(f.contraflow for f in facts),
        bike_width_ft=min(widths) if widths else None,
        parking_lanes=max(parking) if parking else None,
        parking_width_ft=min(parking_widths) if parking_widths else None,
        lane_beside_parking=lane_beside_parking,
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
    # Where the way's own tags already say what the agency does, in a form the
    # overlay must not rewrite (a bike facility OSM maps as its own way).
    agreements: tuple[str, ...] = ()


def _oneway_tag(tags: Mapping[str, str]) -> bool:
    return tags.get("oneway") in ("yes", "1", "-1", "true")


def _osm_two_way(tags: Mapping[str, str]) -> bool:
    """OSM saying in so many words that the way carries traffic both ways:
    `oneway=no`, or lanes counted in each direction."""
    return tags.get("oneway") == "no" or ("lanes:forward" in tags and "lanes:backward" in tags)


def _osm_separate(tags: Mapping[str, str]) -> bool:
    """The way's bike facility is mapped as its own way (`cycleway*=separate`)."""
    return any(
        value == "separate" for key, value in tags.items() if key.startswith(_CYCLEWAY_PREFIX)
    )


def _write_facility(out: dict[str, str], side: str, rank: int, width_m: float | None) -> None:
    out[f"cycleway:{side}"] = "track" if rank == BIKE_PROTECTED else "lane"
    if rank == BIKE_BUFFERED:
        out[f"cycleway:{side}:buffer"] = "yes"
    if width_m and rank != BIKE_PROTECTED:
        out[f"cycleway:{side}:width"] = str(width_m)


def _facility_tags(facts: WayFacts, one_way: bool, travel_forward: bool) -> dict[str, str]:
    """The `cycleway*` tags the agency's facility reads as on this way; empty where
    it records none the way's riders can use.

    On a one-way the facility running with the traffic is the rider's, on the
    right. One running against it is a contraflow lane only where the street
    itself is one-way by the agency's record (or the agency flags a contraflow
    lane): it lets bicycles ride the other way and is no facility for the rider
    going with the traffic. Where the agency's block is two-way, the other
    direction's lane is the other carriageway's (a divided road's two one-way
    ways share one block), and this way takes nothing from it.
    """
    out: dict[str, str] = {}
    width_m = round(facts.bike_width_ft * METRES_PER_FOOT, 2) if facts.bike_width_ft else None
    if facts.direction_known:
        ahead, behind = facts.bike_forward, facts.bike_backward
        if one_way:
            with_flow, against = (ahead, behind) if travel_forward else (behind, ahead)
            if with_flow:
                _write_facility(out, "right", with_flow, width_m)
            if against and (facts.one_way is True or facts.contraflow):
                out["cycleway:left"] = (
                    "opposite_track" if against == BIKE_PROTECTED else "opposite_lane"
                )
                out["oneway:bicycle"] = "no"
        elif ahead and ahead == behind:
            _write_facility(out, "both", ahead, width_m)
        else:
            # Two-way: the way's own direction runs on its right-hand side.
            if ahead:
                _write_facility(out, "right", ahead, width_m)
            if behind:
                _write_facility(out, "left", behind, width_m)
        return out
    if len(facts.bike) == len(DIRECTIONS):
        rank, side = min(facts.bike.values()), "both"
    elif facts.bike:
        rank, side = next(iter(facts.bike.values())), "right"
    else:
        rank, side = None, None
    if rank:
        _write_facility(out, side, rank, width_m)
    if facts.contraflow and side != "both":
        out["cycleway:left"] = "opposite_lane"
    return out


def overlay(tags: Mapping[str, str], facts: WayFacts, separate_road: bool = False) -> Overlay:
    """The way's tags as the classifier should read them, given its blocks' facts.

    A layer that publishes no bike facility (the Baltimore centerline) has
    nothing to say about one, and the way's own tags stand. So do they where OSM
    maps the way's bike facility as a way of its own, beside it: a
    `cycleway*=separate` tag, or `separate_road` (`routemaker.facility.
    separate_pairs` found the facility's own way alongside). The agency's
    protected lane there is that separate way, and writing it onto the road
    would rate the motor lanes as a track (review r1: 15th Street NW went from
    LTS 3 to 1); it is counted as agreement.
    """
    allow_bike = facts.agency in BIKE_AGENCIES
    out = dict(tags)
    sources: dict[str, str] = {}
    disagreements: list[str] = []
    agreements: list[str] = []
    agency = facts.agency

    # -- one-way: an agency that says one-way where OSM says nothing is believed,
    # in the direction the agency's traffic runs. One that says two-way where
    # OSM says one-way is not, because a divided road's carriageways are one-way
    # ways on a two-way block; and one that says one-way where OSM says in so
    # many words that the way is two-way (`oneway=no`, or lanes counted each
    # way) is not either: a mapper looked (review r1: Key Highway, mapped 3 and
    # 2 lanes, read as one-way). Both are counted.
    osm_oneway = _oneway_tag(tags)
    if facts.one_way is True and not osm_oneway and not _osm_two_way(tags):
        out["oneway"] = "-1" if facts.oneway_forward is False else "yes"
        sources["oneway"] = agency
    else:
        sources["oneway"] = SOURCE_OSM if "oneway" in tags or _osm_two_way(tags) else SOURCE_DEFAULT
        if facts.one_way is False and osm_oneway:
            disagreements.append("oneway: agency two-way, OSM one-way")
        elif facts.one_way is True and not osm_oneway:
            disagreements.append("oneway: agency one-way, OSM two-way")
    one_way = _oneway_tag(out)
    # Which of the way's directions its traffic runs in, on a one-way.
    travel_forward = out.get("oneway") != "-1"

    # -- posted speed
    osm_speed = tags.get("maxspeed")
    if facts.speed_mph is not None and not (agency in SPEED_FILLS_ONLY and osm_speed):
        out["maxspeed"] = f"{facts.speed_mph} mph"
        sources["maxspeed"] = agency
    else:
        sources["maxspeed"] = SOURCE_OSM if osm_speed else SOURCE_DEFAULT
        if facts.speed_mph is not None and osm_speed != f"{facts.speed_mph} mph":
            disagreements.append("maxspeed: agency and OSM differ, OSM's posted speed kept")

    # -- lanes in each direction. The classifier reads the larger of
    # `lanes:forward` and `lanes:backward` where either is present, and `lanes`
    # (halved on a two-way road) otherwise. A slip road keeps its own.
    if facts.lanes_per_direction and not is_link(tags):
        per = facts.lanes_per_direction
        for key in ("lanes", "lanes:forward", "lanes:backward"):
            out.pop(key, None)
        if one_way:
            own = facts.lanes_forward if travel_forward else facts.lanes_backward
            out["lanes"] = str(own or per)
        else:
            out["lanes:forward"] = str(facts.lanes_forward or per)
            out["lanes:backward"] = str(facts.lanes_backward or per)
        sources["lanes"] = agency
    else:
        has_lanes = any(key in tags for key in ("lanes", "lanes:forward", "lanes:backward"))
        sources["lanes"] = SOURCE_OSM if has_lanes else SOURCE_DEFAULT

    # -- bike facility, only where the agency has one to give: its absence is
    # not evidence the OSM lane is gone (a lane painted since the layer was
    # cut), and where the two disagree the report says so.
    has_facility = bool(facts.bike or facts.contraflow)
    separate = separate_road or _osm_separate(tags)
    written: dict[str, str] = {}
    if allow_bike and has_facility and not separate:
        written = _facility_tags(facts, one_way, travel_forward)
    if allow_bike and has_facility and separate:
        sources["bike"] = SOURCE_OSM
        agreements.append("bike facility: OSM maps it as a separate way")
    elif written:
        for key in [k for k in out if k.startswith(_CYCLEWAY_PREFIX)]:
            del out[key]
        out.update(written)
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

    # The count's source is not the overlay's to say: a block's count is used
    # only where no count layer reached the way, so the caller records the
    # count it actually used (`aadt_source`).
    return Overlay(out, sources, tuple(disagreements), tuple(agreements))


def block_count_applies(tags: Mapping[str, str]) -> bool:
    """Whether a block's daily count may stand for the way: not on a slip road,
    which carries a fraction of its parent's traffic (review r1)."""
    return not is_link(tags)


def aadt_source(match) -> str:
    """What `attr_sources` says supplied the count the classifier read: the
    agency of the count actually used (`pipeline.conflation.Match`), or `none`.
    Review r1: the overlay said the block's agency wherever the block had a
    count, while the classifier used DDOT's on 44% of matched DC ways."""
    if match is None:
        return "none"
    return getattr(match, "agency", None) or getattr(match, "source", None) or "none"
