"""How the map reads MDOT SHA's statewide LTS: the owner's rules over SHA's own level.

The owner, 2026-10-30, of Maryland's state layer: "I feel that the MD SHA ratings are
overrated (MoCo is actually pretty good)", then "I feel they are often under-rated" and
"Take a look at the differences between them and MoCo". A review (thread "Recheck Maryland
SHA road ratings"; files in the project's reports/md-sha-ratings/) matched 3,000 mi of SHA's
layer inside Montgomery to the county's own rating, learned how the county rates a road with
each set of SHA's attributes, proposed rules from it, and had skeptic agents try to refute
each. The rules that survived are below; the owner chose "Rules in the build" over owner rows
(2026-10-30), so each is a switch here (`ENABLED`) rather than thousands of rows.

They apply only where SHA's level is the one the map uses: Maryland outside Montgomery
(inside, the county's rating wins, `agency_lts.chosen`). SHA's 5, a ban, is never read
otherwise. Each rule reads only SHA's own attributes (functional class, posted or assumed
speed, through lanes, shoulder widths, bike facility), SHA's traffic count for the stretch
(`MDOT SHA Annual Average Daily Traffic`, joined by route and milepoint), and whether the
stretch lies in a Census urban area.

And one fault in SHA's data, not its judgment (`SECOND_RECORD`): SHA inventories many roads
in both directions, and the second direction's record (route id character 15, "2") has no
traffic count, often an assumed speed where the first has a posted one, and on a divided road
its lanes counted one way only. SHA rates it about 0.6 of a level lower than the first, though
a rider meets the same road; so a second record within `PAIR_DISTANCE_M` of its route's first
takes the first's level.

Pure: nothing here reads a file or the network (`scripts/install_agency_lts.py` does).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise

from routemaker.stress import BUSY_RURAL_HIGHWAY_AADT, BUSY_STREET_MIN_AADT

# Maryland's county code for Baltimore City, the first two characters of a route id.
BALTIMORE_CITY = "24"

# The rules, by id, with the words the road panel shows after "read as LTS n:". No commas:
# the stress rule's commas separate its reasons (`agency_lts.apply`).
RULE_WORDS = {
    "collector-assumed-35": "a two-lane collector where SHA assumed 35 mph",
    "slow-street": "a two-lane street at 30 mph or less",
    "city-collector": "a Baltimore City collector where SHA assumed 35 mph",
    "multilane-or-40": "four or more lanes or a two-lane road posted over 35 mph",
    "shoulder-credit": "a two-lane 35 mph road where SHA credited the shoulder",
    "busy-residential": "a 25 mph street carrying 5000 to 15000 cars a day",
    "rural-collector": "a rural collector carrying 1500 or more cars a day",
    "rural-expressway": "a highway of four or more lanes posted 55 mph or more",
    "busy-rural-two-lane": "a rural two-lane highway carrying 18000 or more cars a day",
    "second-record": "SHA's record for the other direction of the same road",
}

# Which rules the map uses. The owner may strike any of them (2026-10-30: each rule "gets
# its own switch, so you can still strike any of them").
ENABLED = frozenset(RULE_WORDS)

# A second-direction record pairs with its route's first-direction record this close.
# The two lie a median 57 ft (17 m) apart; one-way pairs a block apart do not pair.
PAIR_DISTANCE_M = 40.0


@dataclass(frozen=True)
class Stretch:
    """One SHA record's attributes, as the rules read them."""

    route_id: str
    level: float
    functional_class: int | None
    speed_mph: int | None
    speed_assumed: bool
    lanes: int | None
    shoulder_ft: int | None
    bike_facility: str | None
    aadt: int | None
    urban: bool

    @property
    def county(self) -> str:
        return self.route_id[:2]

    @property
    def second_record(self) -> bool:
        return len(self.route_id) > 14 and self.route_id[14] == "2"

    @property
    def painted_lane(self) -> bool:
        return (self.bike_facility or "").lower() == "standard"

    @property
    def protected_lane(self) -> bool:
        return (self.bike_facility or "").lower() == "protected"


def stretch(properties: Mapping, aadt: int | None, urban: bool) -> Stretch:
    """A record of SHA's layer (its GeoJSON properties) as a `Stretch`."""
    left, right = properties.get("SHOULDER_WD_LT"), properties.get("SHOULDER_WD_RT")
    shoulders = [w for w in (left, right) if w is not None]
    return Stretch(
        route_id=str(properties.get("ROUTEID") or ""),
        level=float(properties["LTS_ADJUSTED"]),
        functional_class=properties.get("FUNCTIONAL_CLASS"),
        speed_mph=properties.get("SPEED_LIMIT") or None,
        speed_assumed=properties.get("SPEEDLIMIT_DERIVED") == 1,
        lanes=properties.get("NUMBER_THRU_LANES") or None,
        # The narrower side: a rider may be on either.
        shoulder_ft=min(shoulders) if len(shoulders) == 2 else None,
        bike_facility=properties.get("BIKE_FACILITY_TYPE"),
        aadt=aadt if aadt and aadt > 0 else None,
        urban=urban,
    )


def _rule(s: Stretch) -> tuple[float, str] | None:
    """The level and rule a first-direction record takes, or None for SHA's own."""
    fc, speed, lanes, aadt = s.functional_class, s.speed_mph, s.lanes, s.aadt
    two_lane = lanes == 2
    if s.level == 5 or speed is None:
        return None
    # Down: two-lane collectors where SHA had no posted speed and assumed 35 mph. Montgomery
    # rates them 3 at every count from 1,500 to 15,000 a day (3 on 56-66% of 67 mi).
    if (
        s.urban
        and s.level == 4
        and two_lane
        and fc in (4, 5, 6)
        and s.speed_assumed
        and speed == 35
        and (aadt is None or aadt <= 15_000)
    ):
        city = s.county == BALTIMORE_CITY
        return (3.5 if aadt and aadt >= 10_000 else 3.0), (
            "city-collector" if city else "collector-assumed-35"
        )
    # Down: two-lane streets at 30 mph or less that SHA rates 4. Montgomery: 2 or 3 below
    # 7,500 a day, 3 on 92% above.
    if s.urban and s.level == 4 and two_lane and fc in (4, 5, 6, 7) and speed <= 30:
        if aadt is not None and aadt >= 15_000:
            return None
        return (2.5 if aadt is None or aadt < 7_500 else 3.0), "slow-street"
    # Up: four or more lanes at 30-45 mph, or two lanes posted 40-45 mph, that SHA rates 3
    # or less. Montgomery: 4 on 71-99%. A painted lane is worth half a step.
    if s.level <= 3 and not s.protected_lane and 30 <= speed <= 45:
        # A two-lane road with a painted lane at 40 mph keeps SHA's level: the owner's
        # own 40 mph lane rule reads it 3 (MD 450 Defense Highway), and Montgomery gives
        # 3 on 72% of such stretches (the owner, 2026-10-31).
        kept = s.painted_lane and speed == 40 and s.level == 3
        fast_two_lane = two_lane and not s.speed_assumed and speed >= 40 and not kept
        if (lanes or 0) >= 4 or fast_two_lane:
            return (3.5 if s.painted_lane else 4.0), "multilane-or-40"
    # Up: urban two-lane 35 mph roads SHA rates 2 for a 4 ft shoulder. Montgomery gives a
    # shoulder no credit: 3 below 10,000 a day, leaning 4 above.
    if (
        s.urban
        and s.level == 2
        and two_lane
        and fc in (4, 5, 6)
        and speed == 35
        and (s.shoulder_ft or 0) >= 4
        and not s.painted_lane
    ):
        if aadt is not None and aadt > 15_000:
            return 4.0, "shoulder-credit"
        return (3.5 if aadt is not None and aadt >= 10_000 else 3.0), "shoulder-credit"
    # Up: 25 mph streets carrying 5,000-15,000 a day that SHA rates 1 or 2: the owner's
    # 1st Street rule (2026-10-30, "make the higher cars/day ones, 2.5"). Not with paint
    # (his R Street call: painted, 2).
    if (
        s.urban
        and s.level <= 2
        and two_lane
        and speed <= 25
        and aadt is not None
        and BUSY_STREET_MIN_AADT <= aadt <= 15_000
        and not s.bike_facility
    ):
        return 2.5, "busy-residential"
    # Up: rural minor collectors carrying 1,500+ a day, speed assumed, that SHA rates 2 or
    # less. Montgomery: 4 on 68% (thin); 3.5, and quiet local roads stay at the rural floor
    # (2026-10-13: "We shouldn't overrate sparsely used rural roads").
    if (
        not s.urban
        and s.level <= 2
        and fc == 6
        and s.speed_assumed
        and aadt is not None
        and aadt >= 1_500
    ):
        return 3.5, "rural-collector"
    # Up: divided highways of four or more lanes posted 55 mph or more, SHA 4: the owner's
    # rural posted expressways at 4.5 (2026-10-17), and urban ones too (2026-10-30: "Urban
    # 55 mph are generally either avoid or 4.5 unless there's a specific reason to keep them").
    if s.level == 4 and fc in (2, 3) and (lanes or 0) >= 4 and not s.speed_assumed and speed >= 55:
        return 4.5, "rural-expressway"
    # Up: rural two-lane principal arterials carrying BUSY_RURAL_HIGHWAY_AADT or more that
    # SHA rates 4: the formula's P7 (`stress.busy_road_steps`) on SHA's roads, so US-15
    # reads 4.5 on both sides of the Potomac (the owner, 2026-10-31: "Yes, same rule in
    # MD"). Three lanes count as two, as the formula reads one lane a direction.
    if (
        not s.urban
        and s.level == 4
        and fc in (2, 3)
        and 2 <= (lanes or 0) <= 3
        and not s.bike_facility
        and aadt is not None
        and aadt >= BUSY_RURAL_HIGHWAY_AADT
    ):
        return 4.5, "busy-rural-two-lane"
    return None


def read_as(s: Stretch, enabled: Iterable[str] = ENABLED) -> tuple[float, str] | None:
    """The level a first-direction (or unpaired) record takes and its rule's id, or None
    where SHA's own level stands. The level is SHA's own where a rule would not change it."""
    found = _rule(s)
    if found is None or found[1] not in set(enabled) or found[0] == s.level:
        return None
    return found


def words(rule: str, level: float) -> str:
    """The road panel's note: "read as LTS 3: a two-lane collector where SHA assumed 35 mph"."""
    return f"read as LTS {level:g}: {RULE_WORDS[rule]}"


# Metres per degree near 39 N, for the short distances pairing needs.
_KY = 110_540.0
_KX = 111_320.0 * math.cos(math.radians(39.0))


def _xy(point) -> tuple[float, float]:
    return point[0] * _KX, point[1] * _KY


def _segment_distance(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def midpoint_lonlat(line) -> tuple[float, float]:
    """The point halfway along a line of [lon, lat], as (lon, lat)."""
    x, y = _midpoint(line)
    return x / _KX, y / _KY


def _midpoint(line) -> tuple[float, float]:
    pts = [_xy(c) for c in line]
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(pts)]
    half, run = sum(lengths) / 2, 0.0
    for (a, b), length in zip(pairwise(pts), lengths, strict=True):
        if run + length >= half and length:
            t = (half - run) / length
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        run += length
    return pts[0]


def pair_second_records(
    records: Mapping[str, tuple[str, list]], max_m: float = PAIR_DISTANCE_M
) -> dict[str, str]:
    """Each second-direction record's first-direction partner: {second id: first id}.

    `records` is {record id: (route id, line)}, a line being [[lon, lat], ...]. A second
    record pairs with the nearest first record of the same route (route id's first 12
    characters: county, type, number) whose line passes within `max_m` of its midpoint."""
    firsts: dict[str, list[tuple[str, list]]] = {}
    for rid, (route, line) in records.items():
        if len(route) > 14 and route[14] != "2" and len(line) > 1:
            firsts.setdefault(route[:12], []).append((rid, [_xy(c) for c in line]))
    pairs = {}
    for rid, (route, line) in records.items():
        if not (len(route) > 14 and route[14] == "2") or len(line) < 2:
            continue
        mid = _midpoint(line)
        best = None
        for first_id, pts in firsts.get(route[:12], ()):
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if not (
                min(xs) - max_m <= mid[0] <= max(xs) + max_m
                and min(ys) - max_m <= mid[1] <= max(ys) + max_m
            ):
                continue
            d = min(_segment_distance(mid, a, b) for a, b in pairwise(pts))
            if d <= max_m and (best is None or d < best[0]):
                best = (d, first_id)
        if best is not None:
            pairs[rid] = best[1]
    return pairs


def point_in_polygons(point, polygons) -> bool:
    """Whether (lon, lat) lies in any polygon; a polygon is (bbox, rings), rings in lon/lat,
    holes by the even-odd rule."""
    x, y = point
    for (x0, y0, x1, y1), rings in polygons:
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            continue
        inside = False
        for ring in rings:
            for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
                if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                    inside = not inside
        if inside:
            return True
    return False
