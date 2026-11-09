"""Bridges and tunnels read straight across in the Climbs layer's elevation profiles.

The ground the Climbs layer reads is USGS 3DEP one-arcsecond (`pipeline.elevation`), a
bare-earth, hydro-flattened model: a bridge deck is taken out of it, so the samples under a
bridge read the creek or river below, and the ground over a tunnel reads the hill above it.
Read as they are, a level bridge over Rock Creek is a dive and a climb, and a Cat 5 climb was
found starting mid-deck (hunt finding E3, 2026-11-08). So `pipeline.climb_layer` reads the
extract's `bridge=*` and `tunnel=*` ways (`is_structure_tags`) and replaces the samples on them
by the straight line between the ground at their two ends (`level`): a deck runs from abutment
to abutment, a tunnel from portal to portal.

The router's own profile needs none of this. Valhalla 3.9.1 already does it (verified in its
source, 2026-11-08): `mjolnir/elevationbuilder.cc` samples a bridge or tunnel edge at its two
ends only, encodes no elevation along it and clamps its grade to 3% either way, and
`tyr/serializers.h` interpolates a route's `elevation` samples linearly across each run of
bridge and tunnel edges. So the hills price, the steep-grade markers, the ascent and the chart,
which read the router's samples (`core.routing.grade_profile`), already see a level deck (hunt
findings E1 and E4: not a defect on 3.9.1).

Pure: no database, no router.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Sequence

# Two structures closer than this, end to start, are one (a bridge of several edges, a
# viaduct over a junction): the samples between them are on the deck too.
JOIN_M = 1.0


def _no(value) -> bool:
    return value in (None, False, "", "no", 0)


def is_structure_tags(tags: dict) -> bool:
    """Whether OSM tags make a way a bridge or a tunnel (any `bridge=*` or `tunnel=*` but
    `no`): a building passage or a culvert's road over it reads level either way."""
    return not _no(tags.get("bridge")) or not _no(tags.get("tunnel"))


def merged(spans: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """The spans in order, with those that touch (within JOIN_M) joined into one."""
    out: list[tuple[float, float]] = []
    for start, end in sorted((min(a, b), max(a, b)) for a, b in spans):
        if out and start - out[-1][1] <= JOIN_M:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def level(
    along: Sequence[float],
    heights: Sequence[float | None],
    spans: Iterable[tuple[float, float]],
) -> list[float | None]:
    """`heights` (at `along` metres, rising) with every sample inside a span replaced by the
    straight line between the last sample at or before its start and the first at or after
    its end (the ground at its ends). Where one end has no ground (the profile starts or ends
    on the structure, or the sample there is None), the other end's height is held level;
    where neither has, the samples are left as they are. A new list."""
    out = list(heights)
    n = len(out)
    for start, end in merged(spans):
        first = bisect.bisect_right(along, start) - 1
        last = bisect.bisect_left(along, end)
        if last - first < 2:
            continue  # no sample inside it
        h0 = out[first] if first >= 0 else None
        h1 = out[last] if last < n else None
        if h0 is None and h1 is None:
            continue
        for k in range(max(first + 1, 0), min(last, n)):
            if h0 is None:
                out[k] = h1
            elif h1 is None:
                out[k] = h0
            else:
                share = (along[k] - along[first]) / (along[last] - along[first])
                out[k] = h0 + (h1 - h0) * share
    return out
