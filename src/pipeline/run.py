"""The weekly rebuild, wired.

`rebuild.run_rebuild` is the generic stage runner; this module supplies the
handlers, so the stage names finally mean something. Until it existed the
pipeline was a library of pure functions that nothing called, and every stage
ordering test asserted an enum against itself.

The two validations the plan requires sit immediately before the swap, and both
guard quiet failures rather than loud ones. Valhalla falls back to its built-in
tag transform without reporting an error if it cannot load the configured Lua
script, so the build asserts the parse log names our file. And a tile build
configured without an elevation directory produces edges with no grade at all,
which makes `use_hills` inert and the Mass Ride grade cap unenforceable, so the
build asserts a known steep edge reports a nonzero grade.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from routemaker.shape import sinuosity
from routemaker.stress import classify, is_rough, is_unpaved

from . import borders, extract, variants, writers
from .rebuild import Stage

logger = logging.getLogger(__name__)

LUA_LOADED_PATTERN = re.compile(r"Using LUA script:\s*(\S+)")


class ValidationFailed(RuntimeError):
    """A pre-swap check did not pass, so the swap must not happen."""


@dataclass
class RebuildContext:
    """State threaded between stages."""

    source_pbf: Path
    work_dir: Path
    staging_schema: str = "staging"
    urban_way_ids: frozenset[int] = frozenset()
    sidepath_bridge_ids: frozenset[int] = frozenset()
    aadt_by_way: dict[int, tuple[int, str]] = field(default_factory=dict)
    ways: list[extract.Way] = field(default_factory=list)
    border_nodes: list[borders.BorderNode] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    build_log: str = ""

    def variant_pbf(self, variant: variants.Variant) -> Path:
        return self.work_dir / f"{variant.value}.osm.pbf"


def classify_ways(context: RebuildContext) -> list[dict]:
    """Stress-classify every way and cut it into segment rows."""
    rows: list[dict] = []
    for way in context.ways:
        aadt, source = context.aadt_by_way.get(way.osm_id, (None, None))
        result = classify(
            way.tags,
            aadt=aadt,
            aadt_source=source,
            urban=way.osm_id in context.urban_way_ids,
        )
        trail = variants.is_trail_class(way.tags, context.sidepath_bridge_ids)
        for ordinal, piece in extract.iter_segments(way):
            from routemaker.geo import Point

            rows.append(
                writers.segment_row(
                    way.osm_id,
                    ordinal,
                    piece,
                    result,
                    sinuosity=sinuosity([Point(lon, lat) for lon, lat in piece]),
                    is_trail_class=trail,
                    is_unpaved=is_unpaved(way.tags),
                    is_rough=is_rough(way.tags),
                    lit=way.tags.get("lit") == "yes" if "lit" in way.tags else None,
                )
            )
    return rows


def assert_lua_script_was_loaded(build_log: str, expected: str) -> None:
    """The guard for Valhalla's silent fallback.

    A key it cannot resolve leaves it using the compiled-in transform, dropping
    every derived tag while routing merely looks a little off - which is the
    hardest kind of failure to attribute after the fact.
    """
    match = LUA_LOADED_PATTERN.search(build_log)
    if match is None:
        raise ValidationFailed(
            "the tile build never logged 'Using LUA script:', so Valhalla fell back "
            "to its built-in transform and every derived tag was dropped"
        )
    loaded = match.group(1)
    # Compared as full paths. Matching on basename alone defeats the check
    # entirely, because Valhalla's own built-in script is also called graph.lua,
    # so the very fallback this guard exists to catch would have passed it.
    if loaded != expected:
        raise ValidationFailed(
            f"the tile build loaded {loaded!r}, not this project's {expected!r}; "
            "derived tags from any other script are not ours"
        )


def assert_elevation_reached_the_tiles(max_grade_on_known_steep_edge: float) -> None:
    """The guard for a tile build configured without an elevation directory.

    Caching the HGT data is not the same as using it: without the directory,
    weighted_grade is never baked onto an edge, use_hills is inert on every
    preset that sets it, and the Mass Ride grade cap has no grade to read.
    """
    if max_grade_on_known_steep_edge <= 0.0:
        raise ValidationFailed(
            "a known steep edge reports zero grade, so the tile build ran without "
            "its elevation directory and every hills dial is inert"
        )


def build_handlers(
    context: RebuildContext,
    run: Callable[[Sequence[str]], str] | None = None,
    sample_grade: Callable[[], float] | None = None,
) -> dict[Stage, Callable[[], None]]:
    """The real handler set. `run` and `sample_grade` are injected so the wiring
    is testable without a Valhalla binary."""
    run = run or _run_command

    def fetch_extract() -> None:
        if not context.source_pbf.exists():
            raise ValidationFailed(f"source extract missing: {context.source_pbf}")
        context.ways = extract.read_ways(context.source_pbf)

    def inject_tags() -> None:
        context.work_dir.mkdir(parents=True, exist_ok=True)

    def insert_border_nodes() -> None:
        allocator = borders.SyntheticNodeIds()
        found: list[borders.BorderNode] = []
        for way in context.ways:
            found.extend(
                borders.find_state_crossings(
                    way.osm_id,
                    way.coordinates,
                    _state_at,
                    allocator,
                    way_name=way.name,
                )
            )
        context.border_nodes = found
        writers.write_border_crossings(found)

    def build_tiles() -> None:
        logs = []
        for variant in variants.Variant:
            per_way_tags: dict[int, dict[str, str]] = {}
            node_lists: dict[int, list[int]] = {}
            dropped: set[int] = set()
            for way in context.ways:
                injected = variants.inject(variant, way.tags, context.sidepath_bridge_ids)
                if injected is None:
                    dropped.add(way.osm_id)
                    continue
                per_way_tags[way.osm_id] = extract.derived_tags(
                    {"trail_class": variants.is_trail_class(way.tags, context.sidepath_bridge_ids)}
                )
            for node in context.border_nodes:
                if node.osm_way_id in dropped:
                    continue
                way = next(w for w in context.ways if w.osm_id == node.osm_way_id)
                node_lists[node.osm_way_id] = borders.insert_nodes_into_way(
                    way.node_ids,
                    [n for n in context.border_nodes if n.osm_way_id == node.osm_way_id],
                )
            target = context.variant_pbf(variant)
            extract.write_extract(
                context.source_pbf,
                target,
                per_way_tags,
                [(n.node_id, n.lon, n.lat, n.tags) for n in context.border_nodes],
                node_lists,
                drop_ways=dropped,
            )
            logs.append(
                run(
                    [
                        "valhalla_build_tiles",
                        "-c",
                        f"valhalla/valhalla-{variant.value}.json",
                        str(target),
                    ]
                )
            )
        context.build_log = "\n".join(logs)

    def classify_stress() -> None:
        context.rows = classify_ways(context)

    def write_segments() -> None:
        writers.write_segments(context.staging_schema, context.rows)

    def validate() -> None:
        assert_lua_script_was_loaded(context.build_log, "/conf/lua/graph.lua")
        assert_elevation_reached_the_tiles(
            sample_grade() if sample_grade else _sample_known_steep_edge(run)
        )

    return {
        Stage.FETCH_EXTRACT: fetch_extract,
        Stage.INJECT_TAGS: inject_tags,
        Stage.INSERT_BORDER_NODES: insert_border_nodes,
        Stage.BUILD_TILES: build_tiles,
        Stage.CLASSIFY_STRESS: classify_stress,
        Stage.WRITE_SEGMENTS: write_segments,
        Stage.VALIDATE: validate,
    }


def _run_command(command: Sequence[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return result.stdout + result.stderr


def _state_at(lon: float, lat: float) -> str | None:
    """Which state a coordinate is in, from the jurisdiction polygons."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT state FROM jurisdiction
               WHERE state IS NOT NULL
                 AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
               LIMIT 1""",
            [lon, lat],
        )
        row = cursor.fetchone()
    return row[0] if row else None


def _sample_known_steep_edge(run: Callable[[Sequence[str]], str]) -> float:  # pragma: no cover
    raise ValidationFailed("no grade sampler was supplied; the elevation check cannot be skipped")
