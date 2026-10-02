#!/usr/bin/env python3
"""Count the one-way ways whose contraflow the no-trail graph closes.

Reads a clipped region extract (read only; nothing is written, no graph is
built) and, for every one-way way, asks upstream's own transform (lua/graph.lua
under LuaJIT, with this project's remap) up to three times:

* with the way's tags as they are, which is the standard graph's reading;
* with the same tags less the bicycle conditionals (`bicycle:conditional`,
  `bicycle:forward:conditional`, `bicycle:backward:conditional`), which tells a
  direction the remap's `remap_conditional_access` opens from one that the
  way's other tags open;
* for a way that is not trail class, with the tags `pipeline.variants.inject`
  gives the no-trail variant.

A way counts as closed when the standard reading lets a bicycle ride against the
traffic and the no-trail reading does not (owner, 2026-10-02, items 192 and
193). Separately, every one-way the standard reading opens against the traffic
through a conditional alone is listed, trail class included: the remap is meant
never to do that unless the way itself grants contraflow.

    python scripts/contraflow_census.py /path/to/source.osm.pbf

Run from the repository root with `src` on the path (`PYTHONPATH=src`). The
lengths are the sum of the way's segments in miles, from the located nodes.

What it checks is the code against the source: it re-runs `inject` and the
transform on the source extract's tags. It does not read a built variant
extract or a graph, so it says what the next build will do with this source,
not what a past build did.

Not measured: an approved access override or an agency street layer. Both write
onto a way's tags after the extract is read, and neither changes what this
reads from the source. Derived `rm:*` tags (the crossings fixture's legality and
the stress penalty) are not given to the transform, since none of them grants a
direction.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import osmium

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from pipeline.variants import (  # noqa: E402
    Variant,
    has_contraflow_tag,
    inject,
    is_motor_oneway,
)

BATCH = 4000
EARTH_RADIUS_M = 6_371_008.8
METRES_PER_MILE = 1609.344

# The keys `routemaker_remap.remap_conditional_access` resolves a direction from.
BICYCLE_CONDITIONAL_KEYS = frozenset(
    {"bicycle:conditional", "bicycle:forward:conditional", "bicycle:backward:conditional"}
)

TAGGED = "named by a contraflow tag"
CONDITIONAL = "opened by a bicycle conditional (remap_conditional_access)"
LANES_BOTH = "lanes on both sides"

LUA_HEADER = """
dofile("lua/graph.lua")
local function access(tags, oneway)
  local _, out = ways_proc(tags, 3)
  local forward, backward = tostring(out and out.bike_forward), tostring(out and out.bike_backward)
  -- (with the traffic, against it): a `oneway=-1` way's traffic runs backward.
  if oneway == "-1" then return backward == "true", forward == "true" end
  return forward == "true", backward == "true"
end
local function check(id, oneway, standard, bare, closed)
  local with_standard, against_standard = access(standard, oneway)
  local _, against_bare = access(bare, oneway)
  local against_closed, with_lost = 0, 0
  if closed then
    local with_closed, against = access(closed, oneway)
    against_closed = against and 1 or 0
    with_lost = (with_standard and not with_closed) and 1 or 0
  end
  io.stdout:write(id, " ", against_standard and 1 or 0, " ", against_bare and 1 or 0, " ",
    against_closed, " ", with_lost, "\\n")
end
"""


def lua_string(value: str) -> str:
    out = []
    for byte in value.encode("utf-8"):
        plain = 32 <= byte < 127 and chr(byte) not in '"\\'
        out.append(chr(byte) if plain else f"\\{byte:03d}")
    return '"' + "".join(out) + '"'


def lua_table(tags: dict[str, str] | None) -> str:
    if tags is None:
        return "nil"
    return "{" + ",".join(f"[{lua_string(k)}]={lua_string(v)}" for k, v in tags.items()) + "}"


def without_conditionals(tags: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in tags.items() if k not in BICYCLE_CONDITIONAL_KEYS}


def shape_of(tags: dict[str, str], against_bare: bool) -> str:
    """Why the standard reading opens a one-way against its traffic: a
    contraflow tag, a conditional the remap resolved onto a direction (the way
    is not open against the traffic without its conditionals), or what is left,
    a facility on both sides, which upstream reads as two-way."""
    if not against_bare:
        return CONDITIONAL
    if has_contraflow_tag(tags):
        return TAGGED
    return LANES_BOTH


def metres(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(points, points[1:], strict=False):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        a = (
            math.sin((p2 - p1) / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
        )
        total += 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
    return total


def run_batch(
    batch: list[tuple[int, str, dict, dict | None]],
) -> dict[int, tuple[int, int, int, int]]:
    script = LUA_HEADER + "".join(
        f"check({way_id}, {lua_string(oneway)}, {lua_table(standard)}, "
        f"{lua_table(without_conditionals(standard))}, {lua_table(closed)})\n"
        for way_id, oneway, standard, closed in batch
    )
    result = subprocess.run(
        ["luajit", "-"],
        input=script,
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "ROUTEMAKER_LUA_DIR": "lua"},
        check=True,
    )
    out = {}
    for line in result.stdout.splitlines():
        way_id, *flags = line.split()
        out[int(way_id)] = tuple(int(flag) for flag in flags)
    return out


def main(path: str) -> None:
    candidates: list[tuple[int, str, dict, dict | None, float]] = []
    processor = osmium.FileProcessor(path, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    total_oneways = backward_tagged = 0
    for way in processor:
        if not isinstance(way, osmium.osm.Way):
            continue
        tags = {tag.k: tag.v for tag in way.tags}
        if "highway" not in tags or not is_motor_oneway(tags):
            continue
        # None for a trail-class way: the no-trail graph drops it, and only the
        # standard reading's conditional check applies to it.
        closed = inject(Variant.NO_TRAIL, tags, way.id)
        if closed is not None:
            total_oneways += 1
            backward_tagged += "bicycle:backward" in tags
        points = [(n.lon, n.lat) for n in way.nodes if n.location.valid()]
        oneway = "-1" if tags.get("oneway") == "-1" else "yes"
        candidates.append((way.id, oneway, tags, closed, metres(points)))

    shapes: Counter[str] = Counter()
    miles: Counter[str] = Counter()
    closed_ways = closed_metres = 0
    still_open = []
    by_conditional = []
    with_flow_lost = 0
    for start in range(0, len(candidates), BATCH):
        batch = candidates[start : start + BATCH]
        answers = run_batch([(w, o, t, c) for w, o, t, c, _ in batch])
        for way_id, _, tags, closed, length in batch:
            against_standard, against_bare, against_closed, with_lost = answers[way_id]
            if against_standard and not against_bare:
                by_conditional.append((way_id, tags, length))
            if closed is None:
                continue
            if against_standard:
                closed_ways += 1
                closed_metres += length
                shape = shape_of(tags, bool(against_bare))
                shapes[shape] += 1
                miles[shape] += length
            if against_closed:
                still_open.append((way_id, tags))
            if with_lost:
                with_flow_lost += 1

    print(f"non-trail one-way ways in the extract: {total_oneways}")
    print(
        f"with contraflow on the standard reading: {closed_ways} ways, "
        f"{closed_metres / METRES_PER_MILE:.2f} miles"
    )
    for shape in sorted(shapes):
        print(f"  {shape}: {shapes[shape]} ways, {miles[shape] / METRES_PER_MILE:.2f} miles")
    print(f"still open after the closure: {len(still_open)}")
    for way_id, tags in still_open[:12]:
        keys = ("cycleway", "bicycle", "oneway", "vehicle", "highway")
        print("   ", way_id, {k: v for k, v in tags.items() if k.startswith(keys)})
    print(f"one-ways the closure shut to the traffic direction as well: {with_flow_lost}")
    print(f"one-ways that carry bicycle:backward (rewritten to none): {backward_tagged}")
    print(
        "one-ways (trail class included) the standard reading opens against the "
        f"traffic by a bicycle conditional alone: {len(by_conditional)}, "
        f"{sum(length for _, _, length in by_conditional) / METRES_PER_MILE:.2f} miles"
    )
    for way_id, tags, _ in by_conditional[:24]:
        keys = ("bicycle", "oneway", "highway", "name", "cycleway")
        print("   ", way_id, {k: v for k, v in tags.items() if k.startswith(keys)})


if __name__ == "__main__":
    main(sys.argv[1])
