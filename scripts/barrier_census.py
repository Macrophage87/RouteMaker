#!/usr/bin/env python3
"""Measure what OpenStreetMap knows about the barriers on the bikeable network.

Backlog 2026-11-12, item 12 (area 07 items 1, 2 and 11): before the route names
every gate, stile, step and walk stretch, and before Cargo and Tandem plan with
the impassable ones left out, measure how much of that the source extract
actually records, so that "no barriers on this route" is never read as "none
mapped". The report is the barrier twin of the 2026-10-11 surface coverage one.

Reads a region extract (read only; nothing is written to the data root, no graph
is built) and prints a Markdown report:

* barrier nodes on the bikeable network, by kind, with how many carry a width
  the remap can read (`maxwidth`, as `lua/routemaker_remap.lua`
  `M.parse_width_m` reads it) and how many carry a width only under another key
  (`width`, `maxwidth:physical`), which the remap does not read today;
* what the remap does with each: a gate (Cargo and Tandem pay their large charge,
  every ride type the small one), a narrow bollard made a gate, or a bollard left
  as street furniture because its width is unmapped;
* kerbs on the network, by `kerb` value;
* steps: ways, miles, and how many carry a ramp (`ramp`, `ramp:bicycle`,
  `ramp:stroller`, `ramp:wheelchair`) or a bicycle tag;
* walk-your-bike stretches (`bicycle=dismount`): ways and miles;
* trail access points: where a trail's end meets a road, and how many of those
  have any barrier tag on the end node or the node next to it.

    python scripts/barrier_census.py --pbf /path/to/source.osm.pbf [--csv barriers.csv]

`--csv` also writes every barrier node on the network (OSM id, kind, latitude,
longitude, the width the remap reads, the other width) so a later step can match
barriers to a route. It is public OSM data, but keep it out of the repository
like every extract-derived listing; it holds no ride data.

Memory: the script keeps only tagged barrier and kerb nodes, the nodes of steps
and walk stretches, and trail end nodes; it never holds the whole network's node
ids, so it runs on the PC's low RAM. It reads the extract three times.

Needs pyosmium (`pip install osmium`). Standalone: it imports nothing from the
repository, so it can be run from a copy of this one file.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

EARTH_RADIUS_M = 6_371_008.8
METRES_PER_MILE = 1609.344
FOOT_M = 0.3048

# `M.NARROW_GAP_M` in lua/routemaker_remap.lua: a bollard narrower than this is made a gate.
NARROW_GAP_M = 1.5
# A tandem's or cargo bike's practical floor; a gap under it is reported apart. Our default,
# unmeasured (a typical cargo bike is 0.6-0.9 m wide at the box; a trike or trailer more).
TIGHT_GAP_M = 1.0

# `M.HARD_BARRIERS` in lua/routemaker_remap.lua: lifted over or squeezed through.
HARD_BARRIERS = frozenset({"kissing_gate", "stile", "turnstile"})
ROAD_HIGHWAYS = frozenset(
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
        "service",
        "road",
    }
)
TRAIL_HIGHWAYS = frozenset({"cycleway", "path", "footway", "bridleway", "track", "pedestrian"})
CLOSED = frozenset({"no", "private", "use_sidepath"})
GRANTS = frozenset({"yes", "designated", "permissive", "dismount"})
RAMP_KEYS = ("ramp", "ramp:bicycle", "ramp:stroller", "ramp:wheelchair")
OTHER_WIDTH_KEYS = ("maxwidth:physical", "width")


def parse_width_m(value: str | None) -> float | None:
    """A width in metres, read exactly as the remap's `M.parse_width_m` reads it; None for
    anything it cannot read (so the census counts what the build will see)."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s", "", value.lower())
    comma = re.fullmatch(r"(\d+),(\d+)", text)
    if comma:
        text = f"{comma.group(1)}.{comma.group(2)}"
    feet_inches = re.fullmatch(r"(\d+\.?\d*)'(\d+\.?\d*)\"?", text)
    if feet_inches:
        return float(feet_inches.group(1)) * FOOT_M + float(feet_inches.group(2)) * FOOT_M / 12
    feet = (
        re.fullmatch(r"(\d+\.?\d*)'", text)
        or re.fullmatch(r"(\d+\.?\d*)ft", text)
        or re.fullmatch(r"(\d+\.?\d*)feet", text)
    )
    if feet:
        return float(feet.group(1)) * FOOT_M
    metres = re.fullmatch(r"(\d+\.?\d*)m?", text)
    return float(metres.group(1)) if metres else None


def way_class(tags: dict[str, str]) -> str | None:
    """ "road", "trail", "steps" or None (not on the bikeable network). A way a bicycle is
    refused on is off it unless its own `bicycle` tag grants one; steps count whatever their
    bicycle tag, since a rider meets them where a path runs into them."""
    highway = tags.get("highway")
    if highway == "steps":
        return "steps"
    if highway not in ROAD_HIGHWAYS and highway not in TRAIL_HIGHWAYS:
        return None
    if highway in ("motorway", "motorway_link") and tags.get("bicycle") not in GRANTS:
        return None
    if tags.get("bicycle") in CLOSED:
        return None
    if tags.get("access") in CLOSED and tags.get("bicycle") not in GRANTS:
        return None
    if tags.get("area") == "yes":
        return None
    return "trail" if highway in TRAIL_HIGHWAYS else "road"


def is_barrier_node(tags: dict[str, str]) -> bool:
    return "barrier" in tags or "kerb" in tags


def remap_reading(tags: dict[str, str]) -> str:
    """What the remap makes of a barrier node (lua/routemaker_remap.lua, `remap_node`), in
    the words the report uses."""
    barrier = tags.get("barrier")
    if barrier in HARD_BARRIERS:
        return "hard barrier, made a gate"
    if barrier == "cycle_barrier":
        return "cycle barrier, made a gate"
    if barrier == "bollard":
        width = parse_width_m(tags.get("maxwidth"))
        if width is None:
            return "bollard, width unmapped: free"
        if width < NARROW_GAP_M:
            return "bollard under 1.5 m, made a gate"
        return "bollard 1.5 m or wider: free"
    if barrier in ("gate", "swing_gate", "lift_gate"):
        return "gate (upstream's reading)"
    if barrier == "kerb" or (barrier is None and "kerb" in tags):
        return "kerb"
    return "other (upstream's reading)"


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


@dataclass
class Census:
    # Pass 1 (ways): node lists of steps and walk stretches, and each trail end with its
    # neighbour (end id -> neighbour ids).
    steps: list[tuple[dict[str, str], list[int]]] = field(default_factory=list)
    dismount: list[list[int]] = field(default_factory=list)
    trail_ends: dict[int, set[int]] = field(default_factory=dict)
    wanted_locations: set[int] = field(default_factory=set)
    ways_by_class: Counter = field(default_factory=Counter)
    # Pass 2 (nodes): tagged barrier and kerb nodes, and the locations pass 1 asked for.
    barriers: dict[int, tuple[dict[str, str], float, float]] = field(default_factory=dict)
    locations: dict[int, tuple[float, float]] = field(default_factory=dict)
    # Pass 3 (ways): which barrier nodes lie on the network (id -> classes), which trail
    # ends meet a road.
    on_network: dict[int, set[str]] = field(default_factory=dict)
    access_points: set[int] = field(default_factory=set)

    # -- pass 1 ------------------------------------------------------------------------
    def way_pass_one(self, tags: dict[str, str], refs: list[int]) -> None:
        kind = way_class(tags)
        if kind is None:
            return
        self.ways_by_class[kind] += 1
        if kind == "steps":
            kept = {k: tags[k] for k in tags if k in RAMP_KEYS or k == "bicycle"}
            self.steps.append((kept, refs))
            self.wanted_locations.update(refs)
        elif tags.get("bicycle") == "dismount":
            self.dismount.append(refs)
            self.wanted_locations.update(refs)
        if kind == "trail" and len(refs) >= 2:
            for end, nxt in ((refs[0], refs[1]), (refs[-1], refs[-2])):
                self.trail_ends.setdefault(end, set()).add(nxt)

    # -- pass 2 ------------------------------------------------------------------------
    def node(self, node_id: int, tags: dict[str, str], lat: float, lon: float) -> None:
        if tags and is_barrier_node(tags):
            self.barriers[node_id] = (tags, lat, lon)
        if node_id in self.wanted_locations:
            self.locations[node_id] = (lat, lon)

    # -- pass 3 ------------------------------------------------------------------------
    def way_pass_two(self, tags: dict[str, str], refs: list[int]) -> None:
        kind = way_class(tags)
        if kind is None:
            return
        for ref in refs:
            if ref in self.barriers:
                self.on_network.setdefault(ref, set()).add(kind)
        if kind == "road":
            for ref in refs:
                if ref in self.trail_ends:
                    self.access_points.add(ref)

    # -- the report --------------------------------------------------------------------
    def length_m(self, refs: list[int]) -> float:
        points = [self.locations[r] for r in refs if r in self.locations]
        return sum(haversine_m(a, b) for a, b in zip(points, points[1:], strict=False))

    def barrier_rows(self) -> list[dict]:
        rows = []
        for node_id in sorted(self.on_network):
            tags, lat, lon = self.barriers[node_id]
            rows.append(
                {
                    "osm_node_id": node_id,
                    "barrier": tags.get("barrier", ""),
                    "kerb": tags.get("kerb", ""),
                    "lat": round(lat, 7),
                    "lon": round(lon, 7),
                    "maxwidth_m": _round(parse_width_m(tags.get("maxwidth"))),
                    "maxwidth_raw": tags.get("maxwidth", ""),
                    "other_width_m": _round(_other_width(tags)),
                    "bicycle": tags.get("bicycle", ""),
                    "access": tags.get("access", ""),
                    "on": "+".join(sorted(self.on_network[node_id])),
                    "remap": remap_reading(tags),
                }
            )
        return rows

    def report(self) -> str:
        rows = self.barrier_rows()
        out: list[str] = ["# Barrier coverage on the bikeable network", ""]
        out.append(
            "Ways on the network: "
            + ", ".join(f"{k} {v:,}" for k, v in sorted(self.ways_by_class.items()))
            + "."
        )
        out.append("")

        # Barrier kinds.
        barriers = [r for r in rows if r["barrier"] and r["barrier"] != "kerb"]
        by_kind = Counter(r["barrier"] for r in barriers)
        out += [
            "## Barrier nodes by kind",
            "",
            "| kind | on network | of which on a trail | maxwidth (readable) | under 1.5 m "
            "| under 1.0 m | width only under another key | no width at all |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for kind, count in by_kind.most_common():
            mine = [r for r in barriers if r["barrier"] == kind]
            readable = [r for r in mine if r["maxwidth_m"] is not None]
            other_only = sum(
                r["maxwidth_m"] is None and r["other_width_m"] is not None for r in mine
            )
            out.append(
                f"| {kind} | {count:,} | {sum('trail' in r['on'] for r in mine):,} "
                f"| {len(readable):,} ({_pct(len(readable), count)}) "
                f"| {sum(r['maxwidth_m'] < NARROW_GAP_M for r in readable):,} "
                f"| {sum(r['maxwidth_m'] < TIGHT_GAP_M for r in readable):,} "
                f"| {other_only:,} "
                f"| {sum(r['maxwidth_m'] is None and r['other_width_m'] is None for r in mine):,} |"
            )
        out.append("")

        reading = Counter(r["remap"] for r in barriers)
        out += ["## What the remap does with them", "", "| reading | nodes |", "|---|---:|"]
        out += [f"| {k} | {v:,} |" for k, v in reading.most_common()]
        out.append("")

        unreadable = Counter(
            r["maxwidth_raw"] for r in barriers if r["maxwidth_raw"] and r["maxwidth_m"] is None
        )
        if unreadable:
            out += [
                "Unreadable `maxwidth` values (most common): "
                + ", ".join(f"`{k}` x{v}" for k, v in unreadable.most_common(10)),
                "",
            ]

        # Kerbs.
        kerbs = [r for r in rows if r["barrier"] == "kerb" or (not r["barrier"] and r["kerb"])]
        kerb_values = Counter(r["kerb"] or "(no kerb value)" for r in kerbs)
        out += [f"## Kerbs on the network: {len(kerbs):,}", "", "| kerb | nodes |", "|---|---:|"]
        out += [f"| {k} | {v:,} |" for k, v in kerb_values.most_common()]
        out.append("")

        # Steps.
        steps_m = sum(self.length_m(refs) for _, refs in self.steps)
        ramp = sum(any(t.get(k) not in (None, "no") for k in RAMP_KEYS) for t, _ in self.steps)
        ramp_bike = sum(t.get("ramp:bicycle") not in (None, "no") for t, _ in self.steps)
        bike_tag = Counter(t.get("bicycle", "(none)") for t, _ in self.steps)
        out += [
            "## Steps",
            "",
            f"{len(self.steps):,} ways, {steps_m / METRES_PER_MILE:,.1f} mi. "
            f"With any ramp tag: {ramp:,} ({_pct(ramp, len(self.steps))}); "
            f"with `ramp:bicycle`: {ramp_bike:,} ({_pct(ramp_bike, len(self.steps))}). "
            "Bicycle tag: " + ", ".join(f"{k} {v:,}" for k, v in bike_tag.most_common()) + ".",
            "",
        ]

        # Walk stretches.
        walk_m = sum(self.length_m(refs) for refs in self.dismount)
        out += [
            "## Walk-your-bike stretches (`bicycle=dismount`)",
            "",
            f"{len(self.dismount):,} ways, {walk_m / METRES_PER_MILE:,.1f} mi.",
            "",
        ]

        # Trail access points.
        flagged = sum(
            1
            for end in self.access_points
            if end in self.barriers or any(n in self.barriers for n in self.trail_ends[end])
        )
        out += [
            "## Trail access points",
            "",
            f"Trail ends that meet a road: {len(self.access_points):,}. With a barrier or kerb "
            f"tag on the end node or the node next to it: {flagged:,} "
            f"({_pct(flagged, len(self.access_points))}).",
            "",
            "Caution: a trail end with no tag is not proof of no barrier; a bollard a few "
            "metres in, or one not mapped at all, does not show here.",
        ]
        return "\n".join(out) + "\n"


def _other_width(tags: dict[str, str]) -> float | None:
    for key in OTHER_WIDTH_KEYS:
        width = parse_width_m(tags.get(key))
        if width is not None:
            return width
    return None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def run(pbf: str) -> Census:
    import osmium  # pyosmium; imported here so the pure functions test without it

    census = Census()

    class WaysOne(osmium.SimpleHandler):
        def way(self, w):  # noqa: ANN001
            census.way_pass_one({t.k: t.v for t in w.tags}, [n.ref for n in w.nodes])

    class Nodes(osmium.SimpleHandler):
        def node(self, n):  # noqa: ANN001
            if n.location.valid():
                tags = {t.k: t.v for t in n.tags} if len(n.tags) else {}
                census.node(n.id, tags, n.location.lat, n.location.lon)

    class WaysTwo(osmium.SimpleHandler):
        def way(self, w):  # noqa: ANN001
            census.way_pass_two({t.k: t.v for t in w.tags}, [n.ref for n in w.nodes])

    print("pass 1 of 3: ways", file=sys.stderr)
    WaysOne().apply_file(pbf)
    print("pass 2 of 3: nodes", file=sys.stderr)
    Nodes().apply_file(pbf)
    print("pass 3 of 3: ways", file=sys.stderr)
    WaysTwo().apply_file(pbf)
    return census


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pbf", required=True, help="the region extract (read only)")
    parser.add_argument("--csv", help="also write every barrier node on the network here")
    parser.add_argument("--out", help="write the Markdown report here (default: stdout)")
    args = parser.parse_args(argv)

    census = run(args.pbf)
    text = census.report()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    if args.csv:
        rows = census.barrier_rows()
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            fields = list(rows[0]) if rows else ["osm_node_id"]
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
