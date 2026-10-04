"""Smoothing a street's traffic count along its length (OWNER-DECISIONS 285, 296).

A count is a point measurement that conflation attributes to the way it lands
on. Where two agencies, or two vintages, disagree about one street, a single
block can carry a count that its neighbours do not, and the volume gates in
`routemaker.stress` (VOLUME_QUIET 1,500 and VOLUME_BUSY 8,000) then flip that one
block a tier on a number the rest of the street does not support. The owner's
case: 1st Street NW from Q Street to Quincy Place, 110 m, carries DDOT's
10,665 between neighbours at 7,520, and classified LTS 3 where the blocks either
side are LTS 2 ("It's a fairly low stress road", decision 285).

Lower only (decision 303, the owner: "Keep it LTS 4, and only lower ratings. In most
cases, the smoothing is probably bunching by the intersection. Given that our routing
is a sum of intersection stress and route stress, we don't want to double count."): a
count is replaced only where the median is lower than it, so smoothing removes a
count that is probably an intersection's volume attributed to one block and never
adds volume to a block that counted less.

The fix is to the data, not to a threshold (decision 296: "keep the current
rules as is"; the owner can veto it, which is `RebuildContext.smooth_volume`).
The count a way's volume gate reads is the length-weighted median of the counts
of the ways on the same street within `WINDOW_M` of it, taken only where that
window holds at least `MIN_WAYS` ways and `MIN_LENGTH_M` of road, so a street
with two counted blocks is left as the agencies counted it. A median rather than
a mean, so a single outlier of any size is outvoted instead of dragging the
neighbours; length-weighted, so a 14 m stub does not outvote a 400 m block.

"The same street" is the name without its quadrant (`1st Street Northwest` and
`1st Street Northeast` are one street's two sides of the Capitol), in the same
jurisdiction, so a Virginia count never smooths a District street that shares a
name. Only a way whose count is higher than the median is replaced, and only ways
that carry a count are candidates; a way with no count stays without one.

`Match.raw_aadt` keeps what the agency counted. Only the link's volume gate reads
the median: the rebuild publishes the agency's count in `segment.volume_aadt`, and
keeps the tier on it (`StressResult.unsmoothed_tier`) for the junction model, so the
volume bunched at the intersection is charged at the intersection and only there
(ARTERIAL review r0, SF1; the owner's own reason in 303). `Match.agency` and `year`
stay those of the replaced count: the median can come from any neighbour, and
which segments a source touched is a statement about the count that was
replaced, which is the more conservative reading of the credit.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace

from routemaker.classes import TRAIL_CLASS_HIGHWAY
from routemaker.geo import EARTH_RADIUS_M
from routemaker.streets import street_key

WINDOW_M = 400.0
MIN_WAYS = 3
MIN_LENGTH_M = 250.0
# Never counted as the street: a driveway's count says nothing about the street
# it opens on, and a trail is not on the road's volume at all.
EXCLUDED_HIGHWAY = TRAIL_CLASS_HIGHWAY | {"service"}
_CELL_M = 100.0


@dataclass(frozen=True)
class Smoothed:
    """One count that was replaced, for the report."""

    way_id: int
    street: str
    raw: int
    smoothed: int
    ways: int
    length_m: float


@dataclass(frozen=True)
class SmoothingReport:
    counted_ways: int = 0
    candidate_ways: int = 0
    replaced: tuple[Smoothed, ...] = ()

    def to_csv(self, stress_by_way: Mapping[int, object] | None = None) -> str:
        """One line per replaced count, for `<DATA_ROOT>/rebuild/reports/
        aadt-smoothing.csv`: the agency's count, the street's median the link was
        classified on, the window, whether a volume gate lay between them, and,
        given the classified tiers, the link's tier and the tier on the agency's
        count (what the junction model reads)."""
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            ["way_id", "street", "raw_aadt", "smoothed_aadt", "ways_in_window",
             "window_length_m", "crosses_volume_gate", "link_tier", "tier_on_raw_count"]
        )  # fmt: skip
        for item in self.replaced:
            stress = (stress_by_way or {}).get(item.way_id)
            tier = int(stress.tier) if stress is not None else ""
            raw_tier = getattr(stress, "unsmoothed_tier", None) if stress is not None else None
            writer.writerow(
                [
                    item.way_id,
                    item.street,
                    item.raw,
                    item.smoothed,
                    item.ways,
                    round(item.length_m),
                    "yes" if crosses_volume_gate(item.raw, item.smoothed) else "no",
                    tier,
                    int(raw_tier) if raw_tier is not None else tier,
                ]
            )
        return out.getvalue()

    def summary(self) -> str:
        return (
            f"AADT smoothing (400 m, same street, at least 3 ways and 250 m): "
            f"{len(self.replaced)} of {self.counted_ways} counts replaced by the street's "
            "length-weighted median"
        )


def crosses_volume_gate(raw: int, smoothed: int) -> bool:
    """Whether the two counts fall either side of a volume threshold of the
    classifier, so the replacement can have moved the tier. The gates as
    `routemaker.stress` writes them: quiet is `<= VOLUME_QUIET` (so 1,501 is
    the first count that is not), busy is `>= VOLUME_BUSY`, and the urban
    two-way floor is `> URBAN_TWO_WAY_BUSY_AADT` (so 8,001 is the first count
    over it)."""
    from routemaker.stress import URBAN_TWO_WAY_BUSY_AADT, VOLUME_BUSY, VOLUME_QUIET

    gates = (VOLUME_QUIET + 1, VOLUME_BUSY, URBAN_TWO_WAY_BUSY_AADT + 1)
    return any((raw >= gate) != (smoothed >= gate) for gate in gates)


def _project(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return (
        math.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(lat0)),
        math.radians(lat) * EARTH_RADIUS_M,
    )


def midpoint_and_length(coords) -> tuple[tuple[float, float], float] | None:
    """The point half way along a way's polyline (lon, lat) and its length in
    metres, or None for a way with fewer than two located nodes."""
    if len(coords) < 2:
        return None
    lat0 = coords[0][1]
    pts = [_project(lon, lat, lat0) for lon, lat in coords]
    lengths = [math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False)]
    total = sum(lengths)
    if total <= 0:
        return None
    half, run = total / 2, 0.0
    for index, seg in enumerate(lengths):
        if run + seg >= half and seg > 0:
            t = (half - run) / seg
            (lon0, lat_0), (lon1, lat1) = coords[index][:2], coords[index + 1][:2]
            return (lon0 + (lon1 - lon0) * t, lat_0 + (lat1 - lat_0) * t), total
        run += seg
    return (coords[-1][0], coords[-1][1]), total


def weighted_median(values: Iterable[tuple[int, float]]) -> int:
    """The length-weighted median of (value, weight) pairs: the smallest value
    at which the cumulative weight reaches half."""
    ordered = sorted(values)
    half = sum(weight for _, weight in ordered) / 2
    run = 0.0
    for value, weight in ordered:
        run += weight
        if run >= half:
            return value
    return ordered[-1][0]


def smooth(
    ways: Iterable,
    aadt_by_way: Mapping[int, object],
    jurisdiction_of: Callable[[int], str | None] | Mapping[int, str | None],
    *,
    window_m: float = WINDOW_M,
    min_ways: int = MIN_WAYS,
    min_length_m: float = MIN_LENGTH_M,
) -> tuple[dict[int, object], SmoothingReport]:
    """`aadt_by_way` with each count replaced where its street disagrees, and
    the report. `ways` need `osm_id`, `tags` and `coordinates`; each value of
    `aadt_by_way` is a `conflation.Match`. Nothing is mutated."""
    lookup = jurisdiction_of if callable(jurisdiction_of) else jurisdiction_of.get
    candidates: dict[tuple[str, str | None], list[tuple[float, float, float, int, int]]] = (
        defaultdict(list)
    )
    placed: dict[int, tuple[str, str | None, float, float]] = {}
    for way in ways:
        match = aadt_by_way.get(way.osm_id)
        if match is None or way.tags.get("highway") in EXCLUDED_HIGHWAY:
            continue
        key = street_key(way.tags.get("name"))
        if key is None:
            continue
        mid = midpoint_and_length(way.coordinates)
        if mid is None:
            continue
        (lon, lat), length = mid
        x, y = _project(lon, lat, 38.9)
        group = (key, lookup(way.osm_id))
        candidates[group].append((x, y, length, match.aadt, way.osm_id))
        placed[way.osm_id] = (*group, x, y)

    grids: dict[tuple[str, str | None], dict[tuple[int, int], list]] = {}
    for group, items in candidates.items():
        grid: dict[tuple[int, int], list] = defaultdict(list)
        for item in items:
            grid[(int(item[0] // _CELL_M), int(item[1] // _CELL_M))].append(item)
        grids[group] = grid

    reach = int(window_m // _CELL_M) + 1
    out = dict(aadt_by_way)
    replaced: list[Smoothed] = []
    for way_id, (key, jurisdiction, x, y) in placed.items():
        grid = grids[(key, jurisdiction)]
        cx, cy = int(x // _CELL_M), int(y // _CELL_M)
        near = [
            item
            for i in range(cx - reach, cx + reach + 1)
            for j in range(cy - reach, cy + reach + 1)
            for item in grid.get((i, j), ())
            if (item[0] - x) ** 2 + (item[1] - y) ** 2 <= window_m**2
        ]
        total = sum(item[2] for item in near)
        if len(near) < min_ways or total < min_length_m:
            continue
        median = weighted_median((item[3], item[2]) for item in near)
        match = aadt_by_way[way_id]
        if median >= match.aadt:
            # Lower only (OWNER-DECISIONS 303): a count above its street's median
            # stands, so smoothing can never raise a tier.
            continue
        out[way_id] = replace(match, aadt=median, raw_aadt=match.aadt)
        replaced.append(Smoothed(way_id, key, match.aadt, median, len(near), total))
    report = SmoothingReport(
        counted_ways=len(aadt_by_way),
        candidate_ways=len(placed),
        replaced=tuple(sorted(replaced, key=lambda r: r.way_id)),
    )
    return out, report
