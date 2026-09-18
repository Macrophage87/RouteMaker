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
import sqlite3
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
    retention,
    source,
    tiles,
    variants,
    writers,
)
from .rebuild import RebuildTimedOut, Stage

logger = logging.getLogger(__name__)

LUA_LOADED_PATTERN = re.compile(r"Using LUA script:\s*(\S+)")
LUA_SCRIPT_PATH = "/conf/lua/graph.lua"

# The prefix `lua/routemaker_remap.lua` writes a refused change under, and the
# thing the comments in that file and in `lua/graph.lua` have always said this
# stage greps the parse log for. It did not: `grep -rn ROUTEMAKER-VIOLATION src/`
# was empty, so a transform that refused a change - a write of `highway` or
# `maxspeed`, a remap that would have denied a bicycle at a border-control node
# - said so to stderr and the rebuild promoted the graph anyway.
#
# Kept as a literal here and pinned against the Lua declaration by a test, since
# the two files cannot share a constant.
VIOLATION_LOG_PREFIX = "ROUTEMAKER-VIOLATION"
# How many offending lines the failure quotes. A systematic violation produces
# one line per element and there is no sense putting a million of them in an
# exception; the count is always reported in full.
REPORTED_VIOLATIONS = 5

# How OSM's `lit` values map to true and false, which is not "yes" against
# everything else.
#
# This is upstream's own table, read out of lua/vendor/graph_upstream.lua:414-423
# rather than remembered, because it is the table that decides what reaches the
# graph: `ways_proc` sets `kv["lit"] = lit[kv["lit"]]` (:1480) and
# src/mjolnir/pbfgraphparser.cc:1909 reads the result. Four values - 24/7,
# automatic, dusk-dawn, sunset-sunrise - name a street that is lit, and
# `tags["lit"] == "yes"` called every one of them unlit. The same expression
# wrote the segment table's `lit` column, which is what the "Prefer lit streets"
# preference reads, so the two halves agreed with each other and disagreed with
# the map.
#
# A value that is not in this table maps to nil upstream, which drops the tag
# rather than asserting either way, so it is left out here too instead of being
# guessed at. `tests/test_lua_remap.py` re-extracts the table from the vendored
# file and compares, so a re-vendor that changes it fails there rather than
# diverging quietly.
LIT_BY_OSM_VALUE = {
    "yes": True,
    "no": False,
    "24/7": True,
    "automatic": True,
    "limited": False,
    "disused": False,
    "dusk-dawn": True,
    "sunset-sunrise": True,
}

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


def lit_value(tags: dict) -> bool | None:
    """Whether a way is lit, by upstream's own reading of its `lit` tag.

    None for an absent tag and for a value upstream does not carry, which is
    upstream's answer too: the tag is dropped rather than turned into a claim
    either way. One derivation for both consumers - the `rm:lit` tag the tile
    build reads and the segment table column the preference reads - so they
    cannot drift apart again.
    """
    return LIT_BY_OSM_VALUE.get(tags.get("lit"))


def new_build_id(now: datetime | None = None, tiles_dir: Path | str | None = None) -> str:
    """The dated tile directory's name. UTC, second resolution, sortable, and
    never one that is already taken under the tiles root: two fires in one
    second would otherwise share a directory (`write_build_config` refuses the
    second, but refusing is a failed rebuild and disambiguating is not).

    The root is the caller's when the caller has one. `RebuildContext` carries
    a `tiles_dir` that a test or a second deployment may have pointed
    elsewhere, and reading `settings.TILES_DIR` here meant the id was chosen
    against one directory and the build written into another: two rebuilds
    against the same real root could pick the same id, which is the collision
    this function exists to prevent.
    """
    root = Path(tiles_dir if tiles_dir is not None else _setting("TILES_DIR"))
    return retention.unique_build_id(now or datetime.now(UTC), retention.taken_build_ids(root))


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
        bridge_ids, unmatched_sidepath = variants.resolve_sidepath_bridge_ids(crossing_rows, ways)
        legality, unmatched_legality = variants.resolve_bridge_bicycle_legality(crossing_rows, ways)
        # One warning over the union of both resolvers, because a crossing the
        # extract does not carry is one fact about one bridge however many of
        # the fixture's columns it silences. Only the sidepath half used to
        # report, so the fourteen rows that carry a legality opinion and no
        # sidepath flag - every row the `rm:bridge_bicycle` tag exists for,
        # including the Theodore Roosevelt Bridge, whose entire effect on the
        # no-trail variant is that column - could resolve against nothing and
        # reach no log at all.
        unmatched = sorted(set(unmatched_sidepath) | set(unmatched_legality))
        if unmatched:
            logger.warning(
                "crossings not found in the extract, so the sidepath rule and the "
                "bridge-legality column are both inert on them: %s",
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
            bridge_bicycle_legal=legality,
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
    # The coverage polygon the clip prefers over the box, when a deployment has
    # one. None everywhere today: the repository carries no polygon file, and
    # the box is what PLAN:13's clip is given until it does.
    coverage_polygon: Path | None = field(default_factory=lambda: _setting("COVERAGE_POLYGON"))
    upstreams: dict[str, str] = field(default_factory=lambda: dict(_setting("VALHALLA_UPSTREAMS")))
    # Empty means "choose one", which `__post_init__` does against this
    # context's own `tiles_dir`. A `default_factory` cannot see another field.
    build_id: str = ""
    # Monotonic-clock instant after which no further stage or binary starts.
    deadline: float | None = None

    reference: ReferenceData | None = None
    # The merged, *unclipped* extract FETCH_EXTRACT produced or reused, which is
    # what `valhalla_build_admins` is given (PLAN:13). Not `source_pbf`: that one
    # is the clip, and an admin database built from it describes administrative
    # areas that stop at the coverage boundary.
    merged_pbf: Path | None = None
    ways: list[extract.Way] = field(default_factory=list)
    ways_by_id: dict[int, extract.Way] = field(default_factory=dict)
    aadt_by_way: dict[int, tuple[int, str]] = field(default_factory=dict)
    stress_by_way: dict[int, object] = field(default_factory=dict)
    border_nodes_by_way: dict[int, list[borders.BorderNode]] = field(default_factory=dict)
    override_report: overrides.OverrideReport | None = None
    rows: list[dict] = field(default_factory=list)
    # Per variant, not one concatenation of the three. A single `.search` over
    # the three logs joined together is satisfied by whichever variant logged
    # the line first, so two variants could have fallen back to Valhalla's
    # built-in transform and the check would still pass.
    build_logs: dict[variants.Variant, str] = field(default_factory=dict)
    disk_gate: tiles.DiskGate | None = None
    elevation_tiles: list[Path] = field(default_factory=list)
    build_configs: dict[variants.Variant, Path] = field(default_factory=dict)
    swap_outcome: promotion.SwapOutcome | None = None
    drift_report: object | None = None

    def __post_init__(self) -> None:
        if not self.build_id:
            self.build_id = new_build_id(tiles_dir=self.tiles_dir)

    def variant_pbf(self, variant: variants.Variant) -> Path:
        return self.work_dir / f"{variant.value}.osm.pbf"

    def require_reference(self) -> ReferenceData:
        if self.reference is None:
            raise ReferenceDataMissing("reference data was never loaded")
        return self.reference


def assert_lua_script_was_loaded(build_log: str, expected: str, where: str) -> None:
    """The guard for Valhalla's silent fallback.

    A key it cannot resolve leaves it using the compiled-in transform, dropping
    every derived tag while routing merely looks a little off.

    `where` names the variant, because this is asked once per variant against
    that variant's own log. Asked once against the three joined together, the
    first match satisfied all three and two variants could have fallen back
    without the check noticing.
    """
    match = LUA_LOADED_PATTERN.search(build_log)
    if match is None:
        raise ValidationFailed(
            f"the {where} tile build never logged 'Using LUA script:', so Valhalla fell back "
            "to its built-in transform and every derived tag was dropped"
        )
    loaded = match.group(1)
    # Compared as full paths: Valhalla's own built-in script is also called
    # graph.lua, so a basename match would pass the very fallback this catches.
    if loaded != expected:
        raise ValidationFailed(
            f"the {where} tile build loaded {loaded!r}, not this project's {expected!r}"
        )


def assert_no_rule_violations(build_log: str, where: str) -> None:
    """The reader `ROUTEMAKER-VIOLATION` never had.

    The transform cannot refuse an element: `LuaTagTransform::Transform` runs
    each entry point under lua_pcall and hands back an empty tag map when it
    fails, so an `error()` guard deletes the element instead of refusing it.
    `lua/routemaker_remap.lua` therefore keeps the element, drops the offending
    change, and writes a line to stderr under a fixed prefix - and both that
    file and `lua/graph.lua` say in as many words that this stage asserts no
    such line appears in the parse log. Nothing did. A guard that fires is the
    remap having tried to write `highway` or `maxspeed`, or to deny a bicycle at
    a border-control node: a graph built around a rule this project states it
    does not break, promoted without anyone being told.

    Read off the build log, which is both streams of `valhalla_build_tiles`: the
    Lua writes to `io.stderr` while Valhalla's own lines go to stdout under
    `mjolnir.logging.type: std_out`.
    """
    offending = [line for line in build_log.splitlines() if VIOLATION_LOG_PREFIX in line]
    if not offending:
        return
    shown = "; ".join(line.strip() for line in offending[:REPORTED_VIOLATIONS])
    more = (
        ""
        if len(offending) <= REPORTED_VIOLATIONS
        else f" (and {len(offending) - REPORTED_VIOLATIONS} more)"
    )
    raise ValidationFailed(
        f"the {where} tile build logged {len(offending)} {VIOLATION_LOG_PREFIX} line(s), so the "
        f"transform refused a change it was asked to make and the graph is not the one this "
        f"project describes: {shown}{more}"
    )


# The table each database is read back through, and the only thing that tells a
# built database from a file of the right shape. Both names are upstream's:
# `valhalla_build_admins` creates `admins` (src/mjolnir/adminbuilder.cc) and
# `valhalla_build_timezones` ships the `tz_world` table its consumers query.
# NOT CONFIRMED AGAINST A REAL BUILD - no Valhalla binary has run here - which
# is why a table that cannot be read is reported with the error SQLite gave
# rather than swallowed.
ADMIN_AND_TIMEZONE_TABLES = {"admin": "admins", "timezone": "tz_world"}


def _sqlite_row_count(path: Path, table: str) -> int:
    """Rows in one table of a SQLite file, read directly.

    Python's own `sqlite3` rather than the `sqlite3` binary through the command
    runner: the pipeline image is not required to carry that binary, and a check
    that silently depends on one would fail for the wrong reason on a box
    without it.

    Opened read-only through a URI so that reading a database cannot create or
    journal one; a path that is not a database raises here and the caller
    reports it.
    """
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def assert_admin_and_timezone_databases_were_built(
    build_configs: dict[variants.Variant, Path],
) -> None:
    """The other half of SF3: the commands ran, and they left something usable.

    `mjolnir.admin` and `mjolnir.timezone` are retargeted into the dated build
    directory, and 3.5.1 does not fail a build that cannot find either - it logs
    "Admin db not found. Not saving admin information." and "Time zone db not
    found. Not saving time zone information." and carries on
    (src/mjolnir/graphbuilder.cc:431-444). The result is a graph whose edges
    carry no timezone, which is invisible until a `date_time` request quietly
    evaluates every conditional restriction against nothing.

    Each database is queried rather than weighed. A non-empty file is a weak
    claim: `valhalla_build_timezones` redirects a shell script's stdout, so a
    script that failed after printing its first progress line leaves a file with
    bytes in it and no schema, and an admin build that parsed an extract with no
    boundary relations - which is exactly what building admins from the *clipped*
    extract tends toward - leaves a perfectly valid database with an empty
    `admins` table. Both read back as a graph with no admin or timezone
    information, and both used to pass this check.
    """
    missing: list[str] = []
    for variant in variants.Variant:
        config_path = build_configs.get(variant)
        if config_path is None:
            missing.append(f"{variant.value}: no build config")
            continue
        config = json.loads(Path(config_path).read_text())
        for key, table in ADMIN_AND_TIMEZONE_TABLES.items():
            path = Path(config["mjolnir"][key])
            if not path.is_file():
                missing.append(f"{variant.value}: mjolnir.{key} = {path} is absent")
                continue
            try:
                rows = _sqlite_row_count(path, table)
            except sqlite3.Error as error:
                missing.append(
                    f"{variant.value}: mjolnir.{key} = {path} is not a database with a "
                    f"{table} table in it ({error})"
                )
                continue
            if rows <= 0:
                missing.append(f"{variant.value}: mjolnir.{key} = {path} holds no {table} rows")
    if missing:
        raise ValidationFailed(
            "the tile build left no usable database at these configured paths, so the graph "
            "carries no admin or timezone information and every date_time request evaluates "
            "its conditional restrictions against nothing: " + "; ".join(missing)
        )


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
        """Produce this week's extract, or reuse the one on disk, then read it.

        Produce: this stage used to check that `<DATA_ROOT>/extracts/source.osm.pbf`
        existed and fail when it did not, so the first rebuild on a fresh
        deployment stopped here and nothing anywhere made the file. Now the
        three Geofabrik state extracts are downloaded, merged and clipped
        (`pipeline.source`, PLAN:13) when what is on disk is missing or older
        than `SOURCE_EXTRACT_MAX_AGE`.

        Reuse: the freshness rule is what keeps a second run in the same week
        from pulling 1-2 GB again, and it is why a rebuild retried after a
        validation failure starts at the tile build's speed rather than the
        network's.
        """
        extracts_dir = context.source_pbf.parent
        # Asked here only to size the gate below, since what the gate has to
        # cover depends on whether an extract is about to be downloaded.
        # `ensure_extract` asks again and is what decides.
        refresh = source.refresh_reason(
            extracts_dir / source.MERGED_NAME,
            extracts_dir / source.CLIPPED_NAME,
            max_age=_setting("SOURCE_EXTRACT_MAX_AGE"),
            force=_setting("SOURCE_EXTRACT_FORCE_REFRESH"),
        )

        # The disk gate, before anything is written *and before the download*.
        # The extract is the largest single thing this rebuild puts on the data
        # volume - three state files, the merge, then the clip, all under
        # <DATA_ROOT>/extracts, which is the volume the gate measures - so a gate
        # placed after the download would be a gate on a volume the rebuild had
        # already filled. With no extract on disk there is nothing to measure,
        # so it is sized from `source.ESTIMATED_BYTES`; check_disk_gate already
        # reserves four times the source size for the build's own three variant
        # extracts and scratch, which covers the production's files as well.
        context.disk_gate = tiles.check_disk_gate(
            context.tiles_dir,
            source.ESTIMATED_BYTES if refresh else context.source_pbf.stat().st_size,
            _setting("REBUILD_MIN_FREE_BYTES"),
            _setting("DISK_GATE_FRACTION"),
            disk_usage=disk_usage,
        )

        produced = source.ensure_extract(
            extracts_dir,
            context.coverage_polygon or context.coverage_bbox,
            run,
            urls=_setting("SOURCE_EXTRACT_URLS"),
            max_age=_setting("SOURCE_EXTRACT_MAX_AGE"),
            force=_setting("SOURCE_EXTRACT_FORCE_REFRESH"),
        )
        # `valhalla_build_admins` reads this one, so its absence is a missing
        # input rather than a detail: PLAN:13 builds admin data from the merged
        # extract before clipping.
        if not produced.merged.is_file():
            raise ReferenceDataMissing(f"merged extract missing: {produced.merged}")
        context.merged_pbf = produced.merged
        if not context.source_pbf.exists():
            raise ReferenceDataMissing(
                f"source extract missing: {context.source_pbf}; the extract stage produced "
                f"{produced.clipped}, so this deployment is configured to read a file "
                "nothing writes"
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
                lit = lit_value(way.tags)
                if lit is not None:
                    derived["lit"] = lit

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
        #
        # The admin and timezone databases are built here too, into the same
        # dated directory, because the retargeted config is what names them and
        # nothing else ever writes there. The timezone database is a function of
        # the world rather than of the extract, so the first variant builds it
        # and the rest copy it.
        if context.merged_pbf is None:
            raise ReferenceDataMissing(
                "no merged extract to build admin data from; FETCH_EXTRACT produces it"
            )
        timezone_source: Path | None = None
        for variant in variants.Variant:
            config_path = tiles.write_build_config(
                context.config_dir, context.tiles_dir, variant, context.build_id
            )
            context.build_configs[variant] = config_path
            timezone_db = Path(json.loads(config_path.read_text())["mjolnir"]["timezone"])
            commands = tiles.tile_build_commands(
                config_path,
                context.variant_pbf(variant),
                admin_pbf=context.merged_pbf,
                timezone_db=timezone_db,
                timezone_source=timezone_source,
            )
            # Kept per variant: the Lua-fallback and violation checks are asked
            # of each variant's own log, and one joined string would let the
            # first match answer for all three.
            context.build_logs[variant] = "\n".join(run(command).log for command in commands)
            timezone_source = timezone_source or timezone_db

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
                        lit=lit_value(way.tags),
                    )
                )
        context.rows = rows
        writers.write_segments(context.staging_schema, rows)

    def validate() -> None:
        if set(context.build_logs) != set(variants.Variant):
            raise ValidationFailed(
                "not every variant produced a build log, so there is nothing to check the "
                f"missing ones against: have {sorted(v.value for v in context.build_logs)}"
            )
        for variant, build_log in context.build_logs.items():
            assert_lua_script_was_loaded(build_log, LUA_SCRIPT_PATH, variant.value)
            assert_no_rule_violations(build_log, variant.value)
        assert_admin_and_timezone_databases_were_built(context.build_configs)
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
) -> tiles.CommandOutput:
    """Run one of the pipeline's binaries, inside whatever time budget remains.

    The budget is the rebuild's own: a wedged valhalla_build_tiles is killed
    when the rebuild's deadline arrives rather than being left for the eight-day
    "nothing completed" alarm.

    The two streams come back separately. Returning `stdout + stderr` was a
    silent break of every validation read: valhalla_service in one-shot mode
    puts the response on stdout and its log on stderr
    (src/valhalla_service.cc:42-44), so the concatenation is JSON followed by
    log lines, and stderr is never empty - src/baldr/graphreader.cc:110 logs the
    loaded tile count and :121-159 warns twice about the traffic extract every
    generated config names and no deployment has. `sample_grade` is the first
    thing VALIDATE calls, so the rebuild died there every week and nothing could
    ever promote. See tiles.CommandOutput.
    """
    timeout = None
    if deadline is not None:
        timeout = deadline - clock()
        if timeout <= 0:
            raise RebuildTimedOut(f"no time left to run {command[0]}")
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
    return tiles.CommandOutput(result.stdout, result.stderr)


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
