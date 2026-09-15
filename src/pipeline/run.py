"""The weekly rebuild, wired.

`rebuild.run_rebuild` is the generic stage runner; this module supplies the
handlers, so the stage names mean something.

The shape of this module is a reaction to how its first version failed. Every
input had a default — an empty urban-area set, an empty sidepath list, an empty
volume table — so the rebuild ran to completion, reported every stage complete,
and produced a map that was plausible and wrong: the whole District graded with
rural statutory speeds, no volume anywhere, and the e-bike variant a byte-for-byte
copy of the standard one. Nothing raised. The tests passed, because they
exercised the functions rather than the pipeline.

So the reference data is a separate object with no defaults at all. A rebuild
that cannot find the urban-area layer, the crossings fixture or the volume layers
fails at the loading stage rather than quietly substituting nothing for them.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from routemaker.geo import Point
from routemaker.shape import sinuosity
from routemaker.stress import classify, is_rough, is_unpaved

from . import borders, conflation, extract, variants, writers
from .rebuild import Stage

logger = logging.getLogger(__name__)

LUA_LOADED_PATTERN = re.compile(r"Using LUA script:\s*(\S+)")
LUA_SCRIPT_PATH = "/conf/lua/graph.lua"


class ValidationFailed(RuntimeError):
    """A pre-swap check did not pass, so the swap must not happen."""


class ReferenceDataMissing(RuntimeError):
    """A required input is absent. Never substituted with an empty default."""


@dataclass(frozen=True)
class ReferenceData:
    """Everything the rebuild needs besides the extract itself.

    No defaults, deliberately. Each of these fields stood in for real data in
    the first version and each produced a specific wrong map when empty.
    """

    # Ways inside a Census urban area. Without it every District street is
    # graded against rural statutory speeds and the road-exposure report becomes
    # a wall of top-tier segments on ordinary 25 mph streets.
    urban_way_ids: frozenset[int]
    # Bridges bike-legal only by a sidepath. Without it the no-trail variant
    # treats them as roadways and can put a mass ride on a bridge sidewalk.
    sidepath_bridge_ids: frozenset[int]
    # Agency volume lines, already normalised to one AADT definition.
    volume_features: tuple[conflation.AgencyFeature, ...]

    @classmethod
    def load(cls, directory: Path) -> ReferenceData:
        urban = directory / "urban-areas.json"
        crossings = directory / "crossings.json"
        volume = directory / "volume.json"
        for path in (urban, crossings, volume):
            if not path.exists():
                raise ReferenceDataMissing(
                    f"{path} is absent; a rebuild without it produces a plausible "
                    "wrong map rather than an error, so it is refused"
                )

        crossing_rows = json.loads(crossings.read_text())
        features = tuple(
            conflation.AgencyFeature(
                feature_id=row["id"],
                coordinates=[tuple(c) for c in row["coordinates"]],
                aadt=int(row["aadt"]),
                source=row["source"],
                year=row.get("year"),
            )
            for row in json.loads(volume.read_text())
        )
        return cls(
            urban_way_ids=frozenset(json.loads(urban.read_text())),
            sidepath_bridge_ids=variants.load_sidepath_bridge_ids(crossing_rows),
            volume_features=features,
        )


@dataclass
class RebuildContext:
    """State threaded between stages."""

    source_pbf: Path
    work_dir: Path
    reference_dir: Path
    staging_schema: str = "staging"

    reference: ReferenceData | None = None
    ways: list[extract.Way] = field(default_factory=list)
    ways_by_id: dict[int, extract.Way] = field(default_factory=dict)
    aadt_by_way: dict[int, tuple[int, str]] = field(default_factory=dict)
    stress_by_way: dict[int, object] = field(default_factory=dict)
    border_nodes_by_way: dict[int, list[borders.BorderNode]] = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)
    build_log: str = ""

    def variant_pbf(self, variant: variants.Variant) -> Path:
        return self.work_dir / f"{variant.value}.osm.pbf"

    def require_reference(self) -> ReferenceData:
        if self.reference is None:
            raise ReferenceDataMissing("reference data was never loaded")
        return self.reference


def assert_lua_script_was_loaded(build_log: str, expected: str) -> None:
    """The guard for Valhalla's silent fallback.

    A key it cannot resolve leaves it using the compiled-in transform, dropping
    every derived tag while routing merely looks a little off.
    """
    match = LUA_LOADED_PATTERN.search(build_log)
    if match is None:
        raise ValidationFailed(
            "the tile build never logged 'Using LUA script:', so Valhalla fell back "
            "to its built-in transform and every derived tag was dropped"
        )
    loaded = match.group(1)
    # Compared as full paths: Valhalla's own built-in script is also called
    # graph.lua, so a basename match would pass the very fallback this catches.
    if loaded != expected:
        raise ValidationFailed(f"the tile build loaded {loaded!r}, not this project's {expected!r}")


def assert_elevation_reached_the_tiles(max_grade_on_known_steep_edge: float) -> None:
    """Caching the HGT data is not the same as using it: with no elevation
    directory, use_hills is inert and the grade cap has no grade to read."""
    if max_grade_on_known_steep_edge <= 0.0:
        raise ValidationFailed(
            "a known steep edge reports zero grade, so the tile build ran without "
            "its elevation directory and every hills dial is inert"
        )


def assert_derived_tags_reached_the_tiles(sentinel_value: str | None, expected: str) -> None:
    """The other half of the plan's guard, which the first version omitted.

    The log line proves a script was loaded; it does not prove the script did
    anything. Reading a known edge back is what proves the derived tags survived
    into the graph.
    """
    if sentinel_value != expected:
        raise ValidationFailed(
            f"a known edge reports {sentinel_value!r} for its derived value, not "
            f"{expected!r}; the transform loaded but produced nothing usable"
        )


def build_handlers(
    context: RebuildContext,
    run: Callable[[Sequence[str]], str] | None = None,
    sample_grade: Callable[[], float] | None = None,
    sample_derived_tag: Callable[[], str | None] | None = None,
    state_at: Callable[[float, float], str | None] | None = None,
) -> dict[Stage, Callable[[], None]]:
    """The real handler set, with the external dependencies injected so the
    wiring is testable without Valhalla."""
    run = run or _run_command
    state_at = state_at or _state_at

    def fetch_extract() -> None:
        if not context.source_pbf.exists():
            raise ReferenceDataMissing(f"source extract missing: {context.source_pbf}")
        context.ways = extract.read_ways(context.source_pbf)
        # Indexed once. The first version scanned the whole way list inside a
        # loop over every border node inside a loop over every variant.
        context.ways_by_id = {way.osm_id: way for way in context.ways}

    def load_reference_data() -> None:
        context.reference = ReferenceData.load(context.reference_dir)

    def conflate_volume() -> None:
        reference = context.require_reference()
        result = conflation.conflate(
            [(way.osm_id, way.coordinates) for way in context.ways],
            reference.volume_features,
        )
        context.aadt_by_way = {
            way_id: (match.aadt, match.source) for way_id, match in result.matched.items()
        }
        # Recorded rather than discarded: two agencies disagreeing about one
        # road, and a count that matched nothing, are both things a reviewer
        # needs to see.
        logger.info(
            "volume conflation: %d matched, %d rejected, %d unmatched",
            len(result.matched),
            len(result.rejected),
            len(result.unmatched_features),
        )

    def classify_stress() -> None:
        reference = context.require_reference()
        for way in context.ways:
            aadt, source = context.aadt_by_way.get(way.osm_id, (None, None))
            context.stress_by_way[way.osm_id] = classify(
                way.tags,
                aadt=aadt,
                aadt_source=source,
                urban=way.osm_id in reference.urban_way_ids,
            )

    def tag_jurisdictions() -> None:
        # Segments carry their authority so the permit workflow can read it
        # without re-running a spatial query per route.
        from django.contrib.gis.geos import LineString

        from .jurisdiction import assign_way

        for way in context.ways:
            if len(way.coordinates) < 2:
                continue
            assignments = assign_way(LineString(way.coordinates, srid=4326))
            way.tags.setdefault(
                "_jurisdictions",
                ",".join(sorted({a.authority for a in assignments})),
            )

    def insert_border_nodes() -> None:
        allocator = borders.SyntheticNodeIds()
        found: list[borders.BorderNode] = []
        for way in context.ways:
            nodes = list(
                borders.find_state_crossings(
                    way.osm_id, way.coordinates, state_at, allocator, way_name=way.name
                )
            )
            if nodes:
                context.border_nodes_by_way[way.osm_id] = nodes
                found.extend(nodes)
        writers.write_border_crossings(found)

    def inject_tags() -> None:
        reference = context.require_reference()
        context.work_dir.mkdir(parents=True, exist_ok=True)

        for variant in variants.Variant:
            per_way_tags: dict[int, dict[str, str]] = {}
            node_lists: dict[int, list[int]] = {}
            dropped: set[int] = set()

            for way in context.ways:
                injected = variants.inject(
                    variant, way.tags, way.osm_id, reference.sidepath_bridge_ids
                )
                if injected is None:
                    dropped.add(way.osm_id)
                    continue

                # The variant's own changes, which the first version computed and
                # then threw away - so the e-bike extract was identical to the
                # standard one and an e-bike route could run where e-bikes are
                # barred.
                changes = {k: v for k, v in injected.items() if way.tags.get(k) != v}

                stress = context.stress_by_way.get(way.osm_id)
                derived = {
                    "trail_class": variants.is_trail_class(
                        way.tags, way.osm_id, reference.sidepath_bridge_ids
                    )
                }
                if stress is not None:
                    derived["stress_tier"] = int(stress.tier)
                if "lit" in way.tags:
                    derived["lit"] = way.tags["lit"] == "yes"

                per_way_tags[way.osm_id] = {**changes, **extract.derived_tags(derived)}

            nodes_for_variant = [
                node
                for way_id, nodes in context.border_nodes_by_way.items()
                if way_id not in dropped
                for node in nodes
            ]
            for way_id, nodes in context.border_nodes_by_way.items():
                if way_id in dropped:
                    continue
                node_lists[way_id] = borders.insert_nodes_into_way(
                    context.ways_by_id[way_id].node_ids, nodes
                )

            extract.write_extract(
                context.source_pbf,
                context.variant_pbf(variant),
                per_way_tags,
                [(n.node_id, n.lon, n.lat, n.tags) for n in nodes_for_variant],
                node_lists,
                drop_ways=dropped,
            )

    def build_tiles() -> None:
        logs = []
        for variant in variants.Variant:
            config = f"valhalla/valhalla-{variant.value}.json"
            logs.append(
                run(["valhalla_build_tiles", "-c", config, str(context.variant_pbf(variant))])
            )
        context.build_log = "\n".join(logs)

    def write_segments() -> None:
        reference = context.require_reference()
        rows: list[dict] = []
        for way in context.ways:
            stress = context.stress_by_way[way.osm_id]
            trail = variants.is_trail_class(way.tags, way.osm_id, reference.sidepath_bridge_ids)
            for ordinal, piece in extract.iter_segments(way):
                rows.append(
                    writers.segment_row(
                        way.osm_id,
                        ordinal,
                        piece,
                        stress,
                        sinuosity=sinuosity([Point(lon, lat) for lon, lat in piece]),
                        is_trail_class=trail,
                        is_unpaved=is_unpaved(way.tags),
                        is_rough=is_rough(way.tags),
                        lit=way.tags.get("lit") == "yes" if "lit" in way.tags else None,
                    )
                )
        context.rows = rows
        writers.write_segments(context.staging_schema, rows)

    def validate() -> None:
        assert_lua_script_was_loaded(context.build_log, LUA_SCRIPT_PATH)
        if sample_grade is None or sample_derived_tag is None:
            raise ValidationFailed(
                "the elevation and derived-tag samplers are required; a validation "
                "that cannot read the built tiles validates nothing"
            )
        assert_elevation_reached_the_tiles(sample_grade())
        assert_derived_tags_reached_the_tiles(sample_derived_tag(), "yes")

    return {
        Stage.FETCH_EXTRACT: fetch_extract,
        Stage.LOAD_REFERENCE_DATA: load_reference_data,
        Stage.CONFLATE_VOLUME: conflate_volume,
        Stage.CLASSIFY_STRESS: classify_stress,
        Stage.TAG_JURISDICTIONS: tag_jurisdictions,
        Stage.INSERT_BORDER_NODES: insert_border_nodes,
        Stage.INJECT_TAGS: inject_tags,
        Stage.BUILD_TILES: build_tiles,
        Stage.WRITE_SEGMENTS: write_segments,
        Stage.VALIDATE: validate,
    }


def _run_command(command: Sequence[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return result.stdout + result.stderr


def _state_at(lon: float, lat: float) -> str | None:
    """Which state a coordinate is in.

    Restricted to the state layer and ordered, so the answer is deterministic.
    Querying every layer meant a park polygon lapping across the river could
    answer instead, and two rows could both contain the point with Postgres free
    to return either - which the bisection then called twenty-four times on the
    same stretch without necessarily converging.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT state FROM jurisdiction
               WHERE layer = 'state' AND state IS NOT NULL
                 AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
               ORDER BY id
               LIMIT 1""",
            [lon, lat],
        )
        row = cursor.fetchone()
    return row[0] if row else None
