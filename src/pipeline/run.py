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

import functools
import json
import logging
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from routemaker.geo import Point
from routemaker.shape import sinuosity
from routemaker.stress import classify, is_rough, is_unpaved

from . import (
    borders,
    conflation,
    elevation,
    extract,
    overrides,
    promotion,
    reconcile,
    tiles,
    variants,
    writers,
)
from .rebuild import RebuildTimedOut, Stage

logger = logging.getLogger(__name__)

LUA_LOADED_PATTERN = re.compile(r"Using LUA script:\s*(\S+)")
LUA_SCRIPT_PATH = "/conf/lua/graph.lua"

# What the derived-tag sentinel must read back. The remap writes cycleway=track
# onto a tier-1 way with no cycleway tag of its own, which Valhalla stores as a
# separated cycle lane; nothing but this project's transform produces that on a
# plain residential street.
DERIVED_SENTINEL_EXPECTED = "separated"

# A way is tagged with an authority only if at least this share of its length
# lies inside it; the dominant authority on each layer is always kept. Below a
# tenth, the overlap is a polygon's edge crossing the way's end - a road that
# clips a park boundary by a few metres - and tagging it puts a park agency on
# the permit list of a ride that never entered the park. `assign_way` returns
# every fraction and says the caller decides; this is the decision.
MIN_JURISDICTION_FRACTION = 0.10


def new_build_id(now: datetime | None = None) -> str:
    """The dated tile directory's name. UTC, second resolution, sortable."""
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def _setting(name: str):
    from django.conf import settings

    return getattr(settings, name)


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

    # Crossing names the fixture has an opinion about and the extract does not
    # carry. Empty on a healthy rebuild; anything here means the sidepath rule is
    # not biting on that bridge and an operator needs told which.
    unmatched_crossings: tuple[str, ...]

    # Per-way roadway bicycle legality from the crossing fixture, for the ways it
    # has an opinion about. A legal fact rather than a routing preference, so
    # `inject_tags` emits it on every variant; a way absent from this mapping is
    # left to OSM's own tagging rather than being asserted either way.
    bridge_bicycle_legal: dict[int, bool]

    @classmethod
    def load(cls, directory: Path, ways: Sequence[extract.Way] = ()) -> ReferenceData:
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
        bridge_ids, unmatched = variants.resolve_sidepath_bridge_ids(crossing_rows, ways)
        if unmatched:
            logger.warning(
                "crossings not found in the extract, so the sidepath rule is inert on them: %s",
                ", ".join(unmatched),
            )
        # A second, deliberately separate warning. "Not found in the extract" and
        # "found, but nobody has confirmed the spelling" are different levels of
        # confidence and an operator cannot act on them the same way; folding
        # them into one line would hide the distinction the fixture's
        # `osm_names_verified` column exists to record.
        unverified = variants.unverified_crossing_names(crossing_rows)
        if unverified:
            logger.warning(
                "crossing names not yet verified against a real extract, so their match "
                "is believed rather than checked: %s",
                ", ".join(unverified),
            )
        return cls(
            urban_way_ids=frozenset(json.loads(urban.read_text())),
            sidepath_bridge_ids=bridge_ids,
            volume_features=features,
            unmatched_crossings=tuple(unmatched),
            bridge_bicycle_legal=variants.resolve_bridge_bicycle_legality(crossing_rows, ways),
        )


@dataclass
class RebuildContext:
    """State threaded between stages.

    Every path and name here defaults from settings rather than from a literal.
    `staging_schema` was the literal "staging" while the swap read
    settings.SEGMENT_SCHEMA_STAGING, so with the environment variables set the
    rebuild wrote its rows into one schema and the swap promoted another, empty
    one - a silent empty promotion rather than an error.
    """

    source_pbf: Path
    work_dir: Path
    reference_dir: Path
    staging_schema: str = field(default_factory=lambda: _setting("SEGMENT_SCHEMA_STAGING"))
    tiles_dir: Path = field(default_factory=lambda: _setting("TILES_DIR"))
    elevation_dir: Path = field(default_factory=lambda: _setting("ELEVATION_DIR"))
    config_dir: Path = field(default_factory=lambda: _setting("VALHALLA_CONFIG_DIR"))
    coverage_bbox: tuple[float, float, float, float] = field(
        default_factory=lambda: tuple(_setting("COVERAGE_BBOX"))
    )
    upstreams: dict[str, str] = field(default_factory=lambda: dict(_setting("VALHALLA_UPSTREAMS")))
    build_id: str = field(default_factory=new_build_id)
    # Monotonic-clock instant after which no further stage or binary starts.
    deadline: float | None = None

    reference: ReferenceData | None = None
    ways: list[extract.Way] = field(default_factory=list)
    ways_by_id: dict[int, extract.Way] = field(default_factory=dict)
    aadt_by_way: dict[int, tuple[int, str]] = field(default_factory=dict)
    stress_by_way: dict[int, object] = field(default_factory=dict)
    border_nodes_by_way: dict[int, list[borders.BorderNode]] = field(default_factory=dict)
    override_report: overrides.OverrideReport | None = None
    rows: list[dict] = field(default_factory=list)
    build_log: str = ""
    disk_gate: tiles.DiskGate | None = None
    elevation_tiles: list[Path] = field(default_factory=list)
    build_configs: dict[variants.Variant, Path] = field(default_factory=dict)
    swap_outcome: promotion.SwapOutcome | None = None
    drift_report: object | None = None

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
    load_overrides: Callable[[], list[overrides.Override]] | None = None,
    disk_usage: Callable | None = None,
    fetch_elevation: Callable[[elevation.TileName, Path], Path] | None = None,
) -> dict[Stage, Callable[[], None]]:
    """The real handler set, one per stage, with the external dependencies
    injected so the wiring is testable without Valhalla.

    Every stage has a handler. The production call is `build_handlers(context)`
    with nothing injected, and that shape has to run: the first version
    returned eleven handlers for thirteen stages and required samplers that the
    production call never passed, so the weekly job raised on every fire. What
    is injectable here is exactly the set of things that touch a binary, a
    network or a disk - the command runner, the two tile readers, the state
    lookup, the override loader, the disk measurement and the 3DEP fetch - and
    each default is the production implementation.
    """
    run = run or functools.partial(_run_command, deadline=context.deadline)
    state_at = state_at or _state_at
    load_overrides = load_overrides or overrides.load_approved
    disk_usage = disk_usage or tiles.shutil.disk_usage
    fetch_elevation = fetch_elevation or elevation.fetch_3dep
    sample_grade = sample_grade or (lambda: _least_grade_across_variants(context, run))
    sample_derived_tag = sample_derived_tag or (lambda: _standard_cycle_lane(context, run))

    def fetch_extract() -> None:
        if not context.source_pbf.exists():
            raise ReferenceDataMissing(f"source extract missing: {context.source_pbf}")
        # The disk gate, before anything is written: a rebuild that cannot fit
        # a second full tile set beside the served one refuses to start rather
        # than filling the volume partway through a build.
        context.disk_gate = tiles.check_disk_gate(
            context.tiles_dir,
            context.source_pbf.stat().st_size,
            _setting("REBUILD_MIN_FREE_BYTES"),
            _setting("DISK_GATE_FRACTION"),
            disk_usage=disk_usage,
        )
        # The staging schema is rebuilt from scratch every week, and it is reset
        # here rather than by the segment writer because the crossings are
        # written into it several stages before the segments are.
        from .schema import reset_segment_schema

        writers.refuse_live_schema(context.staging_schema)
        reset_segment_schema(context.staging_schema)

        context.ways = extract.read_ways(context.source_pbf)
        # Indexed once. The first version scanned the whole way list inside a
        # loop over every border node inside a loop over every variant.
        context.ways_by_id = {way.osm_id: way for way in context.ways}

    def load_reference_data() -> None:
        # Given the ways, because the crossings fixture resolves by name against
        # the extract. FETCH_EXTRACT runs first for exactly this reason.
        context.reference = ReferenceData.load(context.reference_dir, context.ways)

    def ensure_elevation() -> None:
        # Cached across rebuilds and re-validated on each: a truncated tile
        # reads as flat terrain rather than as an error, and the build stage
        # reads whatever is in this directory without complaint.
        context.elevation_tiles = elevation.ensure_tiles(
            context.elevation_dir, context.coverage_bbox, fetch_elevation, run
        )

    def conflate_volume() -> None:
        reference = context.require_reference()
        # The third element is the trail-class flag, and it is what keeps a
        # motor-vehicle AADT off a shared-use path: the Mount Vernon Trail runs
        # 15 m from the GW Parkway, well inside `MAX_SEPARATION_M`, so a trail
        # left in the candidate set can out-rank the roadway on bearing and
        # overlap and then deny the count to both real roadway blocks by
        # exclusivity. `conflate` defaults it to False for the two-element
        # form, so until this call passed it the exclusion did not apply.
        result = conflation.conflate(
            [
                (way.osm_id, way.coordinates, variants.is_trail_class(way.tags))
                for way in context.ways
            ],
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
                ",".join(sorted(authorities_for(assignments, MIN_JURISDICTION_FRACTION))),
            )

    def apply_overrides() -> None:
        """The audited corrections, applied where each kind belongs.

        Until this stage existed the override table was one the admin could edit
        and no stage ever read: a row could be written, reviewed and approved,
        and the graph was built exactly as if it were not there.
        """
        rows = load_overrides()
        access, access_missing = overrides.apply_access(context.ways, rows)
        stress, stress_missing = overrides.apply_stress(context.stress_by_way, rows)
        jurisdiction, jurisdiction_missing = overrides.apply_jurisdiction(context.ways, rows)

        missing = tuple(sorted({*access_missing, *stress_missing, *jurisdiction_missing}))
        if missing:
            # An approved correction that reaches nothing is a correction that is
            # not in force, which is worth an operator's attention rather than a
            # silent no-op.
            logger.warning("approved overrides matched no way in the extract: %s", missing)
        context.override_report = overrides.OverrideReport(
            access=access,
            stress=stress,
            jurisdiction=jurisdiction,
            unmatched_way_ids=missing,
        )

    def insert_border_nodes() -> None:
        allocator = borders.SyntheticNodeIds()
        found: list[borders.BorderNode] = []
        for way in context.ways:
            nodes = list(
                borders.find_state_crossings(
                    way.osm_id, way.located_points(), state_at, allocator, way_name=way.name
                )
            )
            if nodes:
                context.border_nodes_by_way[way.osm_id] = nodes
                found.extend(nodes)
        # Into staging, to be promoted with the segments by the rename. This
        # used to rewrite the live table five stages before the swap.
        writers.write_border_crossings(context.staging_schema, found)

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
                # On every variant, not only the no-trail one: whether OSM's
                # `bicycle` tag bars a bridge's roadway outright is a legal
                # fact, true or false everywhere, and access is not a
                # request-time dial. `graph.lua` already reads this tag
                # (`derived.bridge_bicycle_legal`); this is the emitter it
                # never had. Ways the fixture has no opinion about are left
                # out, so OSM's own tagging stands.
                legal = reference.bridge_bicycle_legal.get(way.osm_id)
                if legal is not None:
                    derived["bridge_bicycle"] = legal
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
        # Each variant builds into its own dated directory through a config
        # derived from its serving config: valhalla_build_tiles has no
        # tile-directory option, so the directory has to come from the file,
        # and the serving config names the graph being served.
        logs = []
        for variant in variants.Variant:
            config_path = tiles.write_build_config(
                context.config_dir, context.tiles_dir, variant, context.build_id
            )
            context.build_configs[variant] = config_path
            for command in tiles.tile_build_commands(config_path, context.variant_pbf(variant)):
                logs.append(run(command))
        context.build_log = "\n".join(logs)

    def write_segments() -> None:
        from .schema import schema_exists

        if not schema_exists(context.staging_schema):
            raise RuntimeError(
                f"{context.staging_schema} does not exist; FETCH_EXTRACT resets it and "
                "must have run first"
            )

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
        assert_elevation_reached_the_tiles(sample_grade())
        assert_derived_tags_reached_the_tiles(sample_derived_tag(), DERIVED_SENTINEL_EXPECTED)

    def swap() -> None:
        context.swap_outcome = promotion.perform_swap(
            context.tiles_dir, context.build_id, context.upstreams
        )

    def reconcile_after_swap() -> None:
        context.drift_report = reconcile.drift_report(
            context.build_id,
            _setting("SEGMENT_SCHEMA_LIVE"),
            _setting("SEGMENT_SCHEMA_RETIRED"),
        )

    handlers = {
        Stage.FETCH_EXTRACT: fetch_extract,
        Stage.LOAD_REFERENCE_DATA: load_reference_data,
        Stage.ELEVATION: ensure_elevation,
        Stage.CONFLATE_VOLUME: conflate_volume,
        Stage.CLASSIFY_STRESS: classify_stress,
        Stage.TAG_JURISDICTIONS: tag_jurisdictions,
        Stage.APPLY_OVERRIDES: apply_overrides,
        Stage.INSERT_BORDER_NODES: insert_border_nodes,
        Stage.INJECT_TAGS: inject_tags,
        Stage.BUILD_TILES: build_tiles,
        Stage.WRITE_SEGMENTS: write_segments,
        Stage.VALIDATE: validate,
        Stage.SWAP: swap,
        Stage.RECONCILE: reconcile_after_swap,
    }
    # A stage added to the enum without a handler here is a rebuild that
    # raises on every fire. Asserted at construction, not at hour six.
    assert set(handlers) == set(Stage), set(Stage) - set(handlers)
    return handlers


def authorities_for(assignments, minimum_fraction: float) -> set[str]:
    """The authorities a way is tagged with: per layer, the largest share
    always, and any other that covers at least `minimum_fraction` of it."""
    by_layer: dict[str, list] = {}
    for assignment in assignments:
        by_layer.setdefault(assignment.layer, []).append(assignment)
    chosen: set[str] = set()
    for layer_assignments in by_layer.values():
        ranked = sorted(layer_assignments, key=lambda a: a.fraction, reverse=True)
        chosen.add(ranked[0].authority)
        chosen.update(a.authority for a in ranked[1:] if a.fraction >= minimum_fraction)
    return chosen


def _least_grade_across_variants(context: RebuildContext, run) -> float:
    """Every variant's build must have baked elevation, so the check is the
    smallest grade any of them reports on the known steep edge."""
    steep = _setting("REBUILD_SENTINEL_STEEP_EDGE")
    grades = [
        tiles.sample_grade(run, context.build_configs[variant], steep)
        for variant in variants.Variant
        if variant in context.build_configs
    ]
    if len(grades) != len(variants.Variant):
        raise ValidationFailed("not every variant has a build config to read back")
    return min(grades)


def _standard_cycle_lane(context: RebuildContext, run) -> str | None:
    config_path = context.build_configs.get(variants.Variant.STANDARD)
    if config_path is None:
        raise ValidationFailed("the standard variant has no build config to read back")
    return tiles.sample_cycle_lane(run, config_path, _setting("REBUILD_SENTINEL_TIER1_EDGE"))


def _run_command(
    command: Sequence[str],
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Run one of the pipeline's binaries, inside whatever time budget remains.

    The budget is the rebuild's own: a wedged valhalla_build_tiles is killed
    when the rebuild's deadline arrives rather than being left for the eight-day
    "nothing completed" alarm.
    """
    timeout = None
    if deadline is not None:
        timeout = deadline - clock()
        if timeout <= 0:
            raise RebuildTimedOut(f"no time left to run {command[0]}")
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
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
