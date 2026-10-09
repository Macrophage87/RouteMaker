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
import itertools
import json
import logging
import re
import shlex
import signal
import sqlite3
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from routemaker import (
    agency_roads,
    bike_lanes,
    cbd,
    corridors,
    divided,
    facility,
    lane_overrides,
    massflow,
    ridetime,
    singletrack,
    speed_corrections,
    surfaces,
    trailaccess,
    zoo,
)
from routemaker.geo import Point
from routemaker.shape import sinuosity
from routemaker.stress import classify, inferred_unpaved, is_rough

from . import (
    aadt_smoothing,
    borders,
    checkpoint,
    conflation,
    discrepancies,
    elevation,
    extract,
    lts_sentinels,
    mass_capacity,
    overrides,
    promotion,
    reconcile,
    rematch,
    restricted_areas,
    retention,
    route_relations,
    source,
    states,
    tiles,
    trail_closures,
    trail_routes,
    variants,
    writers,
)
from .rebuild import RebuildTimedOut, Stage
from .schema import (
    METRES_PER_MILE,
    RIDE_PATH_RUN_MI,
    RIDE_ROAD_RUN_MI,
    ROUTE_LONG_BICYCLE,
    Z10_UNPAVED_RUN_MI,
    Z11_PAVED_RUN_MI,
)

logger = logging.getLogger(__name__)

# How many matched block ids are written to a segment's `attr_sources`.
MAX_RECORDED_BLOCKS = 12
# Where each rebuild writes the DC-against-OSM discrepancy report (OWNER-DECISIONS
# 191), under its work directory: `<DATA_ROOT>/rebuild/reports/` on the host.
DISCREPANCY_REPORT_DIR = "reports"
REMATCH_REPORT_NAME = "override-rematch"
# Beside it: each count the street's median replaced, and what the owner's named
# corridors did (ARTERIAL review r0, SF4).
SMOOTHING_REPORT_NAME = "aadt-smoothing.csv"
CORRIDOR_REPORT_NAME = "named-corridors.md"
# Every way inside a military area, closed or left open, for the owner (owner report
# 2026-10-05; `restricted_areas.military_report_csv`).
MILITARY_REPORT_NAME = "military-closures.csv"
# And every way inside a secured federal compound (owner report 2026-10-06;
# `restricted_areas.secured_closures`), the same columns, `facility` for `installation`.
SECURED_REPORT_NAME = "secured-closures.csv"


def write_reports(work_dir: Path, files: dict[str, str], what: str) -> None:
    """Write report files under `<work_dir>/reports/` (`<DATA_ROOT>/rebuild/
    reports/` on the host), replacing last week's. A report, not a stage's
    output: a failure is logged and never fails the rebuild."""
    try:
        out_dir = work_dir / DISCREPANCY_REPORT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out_dir / name).write_text(text)
    except OSError:
        logger.exception("%s report could not be written", what)


# What one of the two validation reads answers with; see `_read_back`.
_Read = TypeVar("_Read")

LUA_LOADED_PATTERN = re.compile(r"Using LUA script:\s*(\S+)")

# How much of a failed command's output is carried out of `_run_command`.
#
# Bounded because these streams are not: a `valhalla_build_tiles` that dies six
# hours in has written hundreds of thousands of progress lines, and this text
# goes into an exception message, a WARNING record and the Procrastinate job
# row. Twenty because the thing being rescued is the diagnosis a tool prints
# just before it stops - osmium's "Could not detect file format for filename",
# curl's "The requested URL returned error: 404", the merge's multiple-version
# warning - and each of those is a line or two with a little context around it,
# while a hundred would put a screen of progress in front of every reader.
COMMAND_OUTPUT_TAIL_LINES = 20

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

# What the derived-tag sentinel must read back. The facility remap moves a
# painted lane (`cycleway=lane`, which upstream stores as a dedicated cycle
# lane) to upstream's shared class; nothing but this project's transform turns
# a plainly tagged painted lane into "shared".
DERIVED_SENTINEL_EXPECTED = "shared"

# The way the derived sentinel edge lies on, when a deployment knows it. The
# read is narrowed to that way, so that a neighbouring way's own OSM-tagged
# sharrow cannot answer for a transform that derived nothing.
#
# North Pierce Street, Arlington, the way `settings.REBUILD_SENTINEL_DERIVED_EDGE`
# lies on (see the evidence there). If a later extract splits or replaces the
# way, the read finds no edge on it and VALIDATE_TILES refuses, naming this check -
# move the sentinel then, don't drop the id. With none,
# `tiles.sample_cycle_lane` still refuses a trace that spans more than one way.
DERIVED_SENTINEL_WAY_ID: int | None = 8795651

# The weekend graph's own sentinel (`settings.REBUILD_SENTINEL_WEEKEND_EDGE`):
# a road closed to cars at the weekend reads as a separated lane there and only
# there, so a weekend graph derived like the standard one is refused.
WEEKEND_SENTINEL_WAY_ID: int = 696971684
WEEKEND_SENTINEL_EXPECTED = "separated"

# A way is tagged with an authority only if at least this share of its length
# lies inside it; the dominant authority on each layer is always kept. Below a
# tenth, the overlap is a polygon's edge crossing the way's end - a road that
# clips a park boundary by a few metres - and tagging it puts a park agency on
# the permit list of a ride that never entered the park. `assign_way` returns
# every fraction and says the caller decides; this is the decision.
MIN_JURISDICTION_FRACTION = 0.10

# The bicycle-closure gate (VALIDATE_TILES; SINGLETRACK-review-r0, finding 2a).
#
# Valhalla's C++ parser reopened 753 singletrack ways and 27 rated OSM closures
# after the transform had closed them, every Lua check passed, and the build was
# promoted. So VALIDATE_TILES reads a sample of them back from every staged graph,
# with a pedestrian `/locate` and each edge's `access.bicycle`, and a graph
# that leaves any of them open to bicycles is not swapped in.
#
# Bounded on purpose: at most this many probes of each kind, read in one
# one-shot `valhalla_service locate` per graph (four in all), each under its own
# timeout as well as the rebuild's deadline. That is a few seconds per rebuild.
CLOSURE_GATE_SINGLETRACKS = 40
CLOSURE_GATE_OSM_CLOSURES = 20
# And, for the NO-BIKE-PATHS rules (OWNER-DECISIONS 291), this many ways of each
# reason: every rule must reach the tiles, not only the singletrack one. A way
# whose reason the graph reopens on purpose (`trail_closures.OFFROAD_KEEPS`) is
# probed on the other graphs only.
CLOSURE_GATE_PER_REASON = 8
CLOSURE_GATE_READ_TIMEOUT_S = 120
# Written under the rebuild's reports directory for the post-swap probe
# (scripts/probe_bicycle_closures.py; docs/OPERATIONS.md, "Bicycle closures in
# the tiles"): the gate's own probe points, and every singletrack way id.
CLOSURE_PROBES_REPORT = "bicycle-closure-probes.csv"
SINGLETRACK_REPORT = "singletrack-ways.txt"
# Keys upstream's transform reads ahead of, or over, plain `bicycle=no`, so a
# rated OSM closure carrying one may be open by upstream's own reading and is
# not one the gate can hold the graph to. `service=driveway` with no `access`
# opens every mode over the bicycle tag, and any `cycleway*` key may set a
# direction or both. A conditional grant is resolved onto the directional keys
# by the remap itself (`M.remap_conditional_access`), so `bicycle=no` +
# `bicycle:conditional=yes @ (...)` is open in the tile by design.
_OPENS_OVER_BICYCLE_NO = (
    "bicycle:forward",
    "bicycle:backward",
    "bicycle:conditional",
    "bicycle:forward:conditional",
    "bicycle:backward:conditional",
    "vehicle:forward",
    "vehicle:backward",
    "oneway:bicycle",
    "bicycle_road",
    "cyclestreet",
)


def _smallint(value: float | None) -> int | None:
    """A road trait as the segment table's smallint: rounded, or null."""
    return None if value is None else round(value)


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


class CommandFailed(RuntimeError):
    """A binary the rebuild shells out to exited non-zero, with what it said.

    `subprocess.CalledProcessError` carries `.stdout` and `.stderr` on the
    exception object, and nothing read them: its `str()` is the argv and the
    exit status, so every failure of this pipeline's external commands was
    reported as "Command '[...]' returned non-zero exit status 1" and the
    reason was discarded with the object. That covered the first rebuild on a
    fresh deployment end to end - curl on a 404 from a mirror, `osmium merge`
    on "Could not detect file format for filename", gdalwarp on an HGT it could
    not read, and `valhalla_build_tiles` failing hours in - every one of
    which says why on a stream that was captured and thrown away.

    Deliberately not in `config.procrastinate.terminal_causes`, which keeps the
    behaviour a `CalledProcessError` had: a mirror that was briefly unreachable
    or a download that dropped is the failure a retry fixes.
    """

    def __init__(
        self,
        command: Sequence[str],
        returncode: int,
        output: tiles.CommandOutput,
        retries: int = 0,
    ) -> None:
        self.command = list(command)
        self.returncode = returncode
        self.output = output
        self.retries = retries
        # Said in the message, which is what the alert and the job row carry: a
        # failure after a retry is the one that says to build with fewer threads.
        after = f" (after {retries} {'retry' if retries == 1 else 'retries'})" if retries else ""
        super().__init__(
            f"{Path(self.command[0]).name} exited {returncode}{after}: "
            f"{shlex.join(self.command)}\n{output.tail(COMMAND_OUTPUT_TAIL_LINES)}"
        )


class ReferenceDataMissing(RuntimeError):
    """A required input is absent. Never substituted with an empty default."""


# How an operator makes the installed crossings match the image, named in the
# refusal below and in docs/OPERATIONS.md.
REINSTALL_CROSSINGS = (
    "docker compose exec -T rebuild python3 scripts/install_reference_data.py --data-root /data"
)


class InstalledCrossingsStale(ReferenceDataMissing):
    """`<DATA_ROOT>/reference/crossings.json` is not the image's checked-in fixture.

    The rebuild reads the installed copy, which only `install_reference_data.py`
    writes, so deploying a rebuild image with a changed fixture changed nothing
    until someone reinstalled - and nothing said so. The fixture of 2026-09-26
    (Key Bridge's roadway for mass rides only) ran against the older installed
    copy with the Key roadway open to every rider, and the approved access
    overrides for its Virginia approaches then routed ordinary riders onto it.
    A `ReferenceDataMissing`, so the task treats it as terminal: the retry would
    read the same file.
    """


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
    # Bridge roadways a mass ride cannot use (`sidepath_only`), which the
    # no-trail variant drops.
    sidepath_bridge_ids: frozenset[int]
    # Bridge roadways for trails-off rides only (`roadway_mass_ride_only`, the
    # owner's rules of 2026-09-26 for Key Bridge and Memorial Bridge, opened to
    # every trails-off ride on 2026-09-26: "Every type, roadways ok"), which the
    # standard and e-bike variants bar and the no-trail variant keeps.
    mass_ride_only_bridge_ids: frozenset[int]
    # Agency volume lines, already normalised to one AADT definition.
    volume_features: tuple[conflation.AgencyFeature, ...]

    # Crossing names the fixture has an opinion about and the extract does not
    # carry, from both resolvers: a sidepath-only row nothing matched and a
    # legality row nothing matched. Empty on a healthy rebuild; anything here
    # means the sidepath rule or the bridge-legality column is inert on that
    # bridge and an operator needs told which.
    unmatched_crossings: tuple[str, ...]

    # Per-way roadway bicycle legality from the crossing fixture, for the ways it
    # has an opinion about. A legal fact rather than a routing preference, so
    # `inject_tags` emits it on every variant; a way absent from this mapping is
    # left to OSM's own tagging rather than being asserted either way.
    bridge_bicycle_legal: dict[int, bool]

    # Agency street blocks (DC's Roadway Block, Baltimore's street centerline),
    # from `roadway.json`: the posted speed, lanes, one-way, bike facility,
    # parking and count each agency records for a block, which take precedence
    # over OSM's tags where a way lies along them. The one reference file that
    # is optional: a rebuild without it classifies from OSM and the defaults,
    # which is what every rebuild did before the layers were approved, and it
    # logs a warning so the absence is seen. Only `install_reference_data.py
    # --roadway-block/--baltimore-centerline` writes it.
    road_blocks: tuple[conflation.RoadFeature, ...] = ()

    @classmethod
    def load(
        cls,
        directory: Path,
        ways: Sequence[extract.Way] = (),
        *,
        checked_in_crossings: Path | None = None,
    ) -> ReferenceData:
        """Read the three files; with `checked_in_crossings`, refuse a stale copy.

        `checked_in_crossings` is the fixture the running code was written
        against (the image's `fixtures/crossings/potomac-anacostia.json`, from
        `settings.REBUILD_CROSSINGS_FIXTURE`, which the weekly task passes).
        The installed `crossings.json` must say the same thing - compared as
        parsed JSON, so re-indenting is not a difference and any value is - or
        the load is refused with the command that fixes it. None skips the
        check, for callers that install their own synthetic rows.
        """
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
        if checked_in_crossings is not None:
            if not checked_in_crossings.exists():
                raise ReferenceDataMissing(
                    f"{checked_in_crossings} is absent, so the installed {crossings} cannot "
                    "be checked against the fixture this code was written for"
                )
            if json.loads(checked_in_crossings.read_text()) != crossing_rows:
                raise InstalledCrossingsStale(
                    f"{crossings} differs from this image's {checked_in_crossings}: the "
                    "fixture changed and the installed copy was not reinstalled, and the "
                    "rebuild reads only the installed copy. Refused rather than built "
                    "against the old rows. Reinstall it, then rerun the rebuild: "
                    f"{REINSTALL_CROSSINGS}"
                )
        features = tuple(
            conflation.AgencyFeature(
                feature_id=row["id"],
                coordinates=[tuple(c) for c in row["coordinates"]],
                aadt=int(row["aadt"]),
                source=row["source"],
                year=row.get("year"),
                # The precedence tier above and the publishing agency here are
                # two facts and the installer writes both. Only the tier was
                # read, so "state" was all the segment table ever learned about
                # a count and MDOT SHA and VDOT were one source in the published
                # derivative. Absent on a `volume.json` written before the
                # installer emitted it, and left absent rather than backfilled
                # from the tier: an unknown agency is a thing a reviewer can
                # see, a tier wearing an agency's name is not.
                agency=row.get("agency"),
            )
            for row in json.loads(volume.read_text())
        )
        road_blocks = cls.load_road_blocks(directory / "roadway.json")
        bridge_ids, unmatched_sidepath = variants.resolve_sidepath_bridge_ids(crossing_rows, ways)
        legality, unmatched_legality = variants.resolve_bridge_bicycle_legality(crossing_rows, ways)
        mass_ride_ids, unmatched_mass_ride = variants.resolve_mass_ride_only_bridge_ids(
            crossing_rows, ways
        )
        variants.refuse_retired_columns(crossing_rows)
        # One warning over the union of the three resolvers, because a crossing the
        # extract does not carry is one fact about one bridge however many of
        # the fixture's columns it silences. It covers a row pinned to an
        # `osm_way_id` the extract no longer carries as well as a name that
        # matched nothing (owner decision, 2026-09-25): a warning, not a
        # refusal, so the rebuild still runs. Only the sidepath half used to
        # report, so the fourteen rows that carry a legality opinion and no
        # sidepath flag - every row the `rm:bridge_bicycle` tag exists for,
        # including the Theodore Roosevelt Bridge - could resolve against
        # nothing and reach no log at all.
        unmatched = sorted(
            set(unmatched_sidepath) | set(unmatched_legality) | set(unmatched_mass_ride)
        )
        if unmatched:
            logger.warning(
                "crossings not found in the extract, so the sidepath rule, the "
                "bridge-legality column and the mass-ride-only rule are inert on them: %s",
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
            mass_ride_only_bridge_ids=mass_ride_ids,
            volume_features=features,
            unmatched_crossings=tuple(unmatched),
            bridge_bicycle_legal=legality,
            road_blocks=road_blocks,
        )

    @staticmethod
    def load_road_blocks(path: Path) -> tuple[conflation.RoadFeature, ...]:
        """The agency street blocks, or none (with a warning) where not installed."""
        if not path.exists():
            logger.warning(
                "%s is absent, so no agency street layer (DC Roadway Block, Baltimore street "
                "centerline) is conflated: posted speeds, lanes, one-way, bike lanes and "
                "parking come from OSM and the defaults. Install it with "
                "scripts/install_reference_data.py --roadway-block / --baltimore-centerline",
                path,
            )
            return ()
        # Owner-known lane counts where the layer is stale (OWNER-DECISIONS 412).
        overrides = lane_overrides.load()
        return tuple(
            conflation.RoadFeature(
                feature_id=row["id"],
                coordinates=[tuple(c) for c in row["coordinates"]],
                facts=lane_overrides.apply(
                    agency_roads.RoadFacts.from_json(row["facts"]), row["coordinates"], overrides
                ),
            )
            for row in json.loads(path.read_text())
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
    # The checked-in crossings fixture the installed copy under `reference_dir`
    # must match (`ReferenceData.load`). None, the default, skips the check;
    # the weekly task passes `settings.REBUILD_CROSSINGS_FIXTURE`. Not a
    # settings default because every test context installs synthetic rows.
    checked_in_crossings: Path | None = None
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

    # --- Checkpoints (pipeline.checkpoint; OWNER-DECISIONS 459) ------------------
    # The Procrastinate job this attempt belongs to, None outside the worker. A
    # checkpoint is resumed only inside the job that wrote it: the job's own retries
    # and an `unwedge_job` requeue keep the id, a new job gets a new one.
    job_id: int | None = None
    # Off with REBUILD_CHECKPOINTS=0: nothing is written and nothing is resumed.
    checkpoints: bool = field(default_factory=lambda: bool(_setting("REBUILD_CHECKPOINTS")))
    # The classification manifest this attempt means to resume. FETCH_EXTRACT checks
    # it against the world as it is now and either adopts it (`resumed`) or
    # deletes it and starts fresh under a new build id.
    resume: dict | None = None
    resumed: bool = False
    # The build id the adopted manifest names, kept apart from `build_id` so the
    # guarded delete has a second source to check it against.
    resumed_build_id: str | None = None
    # A resume was offered and refused (an input moved): this attempt started fresh,
    # so what it checkpoints is not progress on an earlier attempt (459a's retry).
    resume_refused: bool = False
    # Drop the classification's in-memory data once VALIDATE_SEGMENTS has passed, so
    # the tile build has that memory: nothing after it reads them (a resumed attempt
    # never loads them). Set by the worker; off by default so a test can still read
    # a whole run's context afterwards.
    release_after_classification: bool = False
    # A resumed attempt whose staging-only validation numbers changed runs those
    # checks again; the rest of VALIDATE_SEGMENTS needs a context it does not load.
    revalidate_staging: bool = False
    # What the attempt did with its checkpoints, for the log and the run row.
    resume_note: str = ""
    checkpoints_written: int = 0
    graphs_reused: list[str] = field(default_factory=list)
    graphs_built: list[str] = field(default_factory=list)
    hasher: checkpoint.Hasher = field(default_factory=checkpoint.Hasher)
    # The directories whose content the classification fingerprint digests.
    code_roots: dict[str, Path] = field(
        default_factory=lambda: {
            name: Path(_setting("BASE_DIR")) / name
            for name in ("src", "fixtures", "lua", "valhalla")
        }
    )
    # The inputs as they were when the extract was in place and nothing had been read:
    # the checkpoint is written only if they are still the same at the end.
    start_fingerprint: dict | None = None
    # The sample of closures the graphs must keep closed, and the singletrack ways
    # the post-swap probe reads. Computed by VALIDATE_SEGMENTS, which has the ways;
    # VALIDATE_TILES, which does not need them, reads these.
    closure_probes: list | None = None
    # The override report's text, when the report itself was not built in this process.
    override_summary: str | None = None

    reference: ReferenceData | None = None
    # The merged, *unclipped* extract FETCH_EXTRACT produced or reused, which is
    # what `valhalla_build_admins` is given (PLAN:13). Not `source_pbf`: that one
    # is the clip, and an admin database built from it describes administrative
    # areas that stop at the coverage boundary.
    merged_pbf: Path | None = None
    ways: list[extract.Way] = field(default_factory=list)
    ways_by_id: dict[int, extract.Way] = field(default_factory=dict)
    # The whole `Match`, not `(aadt, tier)`. The stage that reads this is the
    # last one that could record where a count came from, and the pair dropped
    # the agency and the year on the floor.
    aadt_by_way: dict[int, conflation.Match] = field(default_factory=dict)
    # What the agency street blocks say about each way they were matched to
    # (`conflate_volume`), and the way's tags as the classifier reads them once
    # that is overlaid: a statement about the rider's stress. Only ways a block
    # reached are here.
    road_facts_by_way: dict[int, agency_roads.WayFacts] = field(default_factory=dict)
    class_tags_by_way: dict[int, dict[str, str]] = field(default_factory=dict)
    # The one thing of the overlay the graph takes too: the direction of
    # traffic the District's record decided (OWNER-DECISIONS 216, "Enforce on
    # all maps"), as the keys it changes in the way's OSM tags
    # (`variants.agency_routing_tags`), laid over them on every variant by
    # `inject_tags`. Only ways whose direction the record changed are here.
    routing_tags_by_way: dict[int, dict[str, str]] = field(default_factory=dict)
    road_attr_sources: dict[int, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    road_disagreements: dict[int, tuple[str, ...]] = field(default_factory=dict)
    stress_by_way: dict[int, object] = field(default_factory=dict)
    # Whether a count is replaced by its street's median before classification
    # (`pipeline.aadt_smoothing`; OWNER-DECISIONS 285, 296: a data-quality fix
    # the owner can veto, which this is). To veto: set this default to False,
    # commit, and rebuild the pipeline image; the next rebuild classifies every
    # link on the agency's count (docs/OPERATIONS.md, "AADT smoothing, named
    # corridors and the override re-match").
    smooth_volume: bool = True
    # The counts as the agencies gave them, kept when smoothing replaced any, and
    # what smoothing and the named corridors did (for the rebuild report).
    aadt_raw_by_way: dict[int, conflation.Match] = field(default_factory=dict)
    smoothing_report: aadt_smoothing.SmoothingReport | None = None
    corridor_report: corridors.CorridorReport | None = None
    # The owner's facility class per way (`routemaker.facility`), and the ride
    # times in which a timed closure makes a road car-free. Computed once, after
    # the access overrides, by the first stage that needs them.
    facility_by_way: dict[int, str] = field(default_factory=dict)
    car_free_by_way: dict[int, frozenset[str]] = field(default_factory=dict)
    # The route level of each way in an OSM route relation (`pipeline.trail_routes`).
    trail_routes: dict[int, int] = field(default_factory=dict)
    # Ways in a route=mtb relation (OWNER-DECISIONS 378).
    mountain_bike_ways: set[int] = field(default_factory=set)
    # The name of the route relation each way is in (`pipeline.trail_routes`).
    route_names: dict[int, str] = field(default_factory=dict)
    # Sidewalks bicycles may not ride: the CBD rule (routemaker.cbd).
    cbd_sidewalks: set[int] = field(default_factory=set)
    # Mountain-bike singletrack, which every ride type avoids (routemaker.singletrack).
    singletracks: set[int] = field(default_factory=set)
    # Every `rm:no_bicycle` reason of the NO-BIKE-PATHS rules (routemaker.trailaccess,
    # routemaker.zoo, pipeline.trail_closures), cbd_sidewalk and singletrack
    # included, by way; the short dismount connectors routing keeps and the route
    # description flags; the Zoo spur (destination-only); and the ways a future
    # mountain-bike mode would ride.
    no_bicycle: dict[int, str] = field(default_factory=dict)
    walk_bike: set[int] = field(default_factory=set)
    destination_only: set[int] = field(default_factory=set)
    mtb_only: set[int] = field(default_factory=set)
    # Ways classified at a curated speed limit (`routemaker.speed_corrections`).
    speed_corrected: set[int] = field(default_factory=set)
    # Ways classified with a curated bike lane (`routemaker.bike_lanes`; OWNER-DECISIONS 433).
    bike_lanes_marked: set[int] = field(default_factory=set)
    # The ways the stress map leaves out by their length or their place
    # (pipeline.restricted_areas): the short unnamed paths
    # (facility.short_paths_to_hide), the roads inside a military base, every
    # way inside a cemetery, and a parking lot's own ways.
    short_paths_hidden: set[int] = field(default_factory=set)
    # The ways inside a cemetery, routed only to or from a point inside one
    # (`rm:cemetery`; OWNER-DECISIONS 98).
    cemetery_ways: set[int] = field(default_factory=set)
    # Every way inside a military area, and whether the rule closed it
    # (`restricted_areas.military_closures`; the rebuild's military-closures.csv).
    military_ways: list[restricted_areas.MilitaryWay] = field(default_factory=list)
    # The ways an approved access override wrote a bicycle key on (APPLY_OVERRIDES):
    # inside a military area, only these reopen by evidence (OWNER-DECISIONS 330, 437).
    bicycle_override_ways: frozenset[int] = frozenset()
    # Open networks inside a base that meet the outside network at two or more points
    # for no listed reason (`restricted_areas.through_networks`); VALIDATE_SEGMENTS
    # refuses any.
    military_through: list[tuple[list[int], list[int]]] = field(default_factory=list)
    # The same for a secured federal compound (`restricted_areas.secured_closures`;
    # owner report 2026-10-06; the rebuild's secured-closures.csv), and its open
    # networks through; VALIDATE_SEGMENTS refuses any.
    secured_ways: list[restricted_areas.MilitaryWay] = field(default_factory=list)
    secured_through: list[tuple[list[int], list[int]]] = field(default_factory=list)
    # The curated compounds (`restricted_areas.SECURED_AREAS`) the extract has no area for.
    secured_missing: list[str] = field(default_factory=list)
    border_nodes_by_way: dict[int, list[borders.BorderNode]] = field(default_factory=dict)
    override_report: overrides.OverrideReport | None = None
    # The fixture ways an approved access override wrote a `bicycle`,
    # `bicycle:forward` or `bicycle:backward` key onto, and the directions it
    # wrote them for, which `inject_tags` reads: the crossings fixture's
    # legality column is withheld where a row overruled it in both directions,
    # so the audited table outranks the checked-in file rather than the other
    # way round, and kept where a row overruled one, so the fixture still
    # decides the direction no reviewer spoke to. Set by the override stage and
    # empty until it runs.
    bicycle_override_directions: dict[int, frozenset[str]] = field(default_factory=dict)
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

    def checkpoint_summary(self) -> str:
        """One sentence on what this attempt kept or reused, for the run row."""
        parts = []
        if self.resume_note:
            parts.append(self.resume_note)
        if self.graphs_reused or self.graphs_built:
            parts.append(
                "graphs reused: "
                + (", ".join(self.graphs_reused) or "none")
                + "; built: "
                + (", ".join(self.graphs_built) or "none")
            )
        if self.hasher.seconds >= 1:
            parts.append(f"hashing took {self.hasher.seconds:.0f} s")
        return "; ".join(parts)

    def release_classification(self) -> None:
        """Let go of what only the classification stages and VALIDATE_SEGMENTS read.

        The staging schema and the variant extracts hold the result from here on;
        VALIDATE_TILES reads the closure probes and the singletracks, which stay.
        """
        import gc

        for name in (
            "ways",
            "ways_by_id",
            "aadt_by_way",
            "aadt_raw_by_way",
            "road_facts_by_way",
            "class_tags_by_way",
            "routing_tags_by_way",
            "road_attr_sources",
            "road_disagreements",
            "stress_by_way",
            "facility_by_way",
            "car_free_by_way",
            "trail_routes",
            "route_names",
            "no_bicycle",
            "border_nodes_by_way",
            "military_ways",
            "secured_ways",
        ):
            setattr(self, name, type(getattr(self, name))())
        self.reference = None
        gc.collect()

    def require_reference(self) -> ReferenceData:
        if self.reference is None:
            raise ReferenceDataMissing("reference data was never loaded")
        return self.reference


def assert_lua_script_was_loaded(build_log: str, build_config: Path, where: str) -> None:
    """The guard for Valhalla's silent fallback.

    A key it cannot resolve leaves it using the compiled-in transform, dropping
    every derived tag while routing merely looks a little off.

    `where` names the variant, because this is asked once per variant against
    that variant's own log. Asked once against the three joined together, the
    first match satisfied all three and two variants could have fallen back
    without the check noticing.

    What the log is compared against is read out of `build_config` - the file
    this variant's `valhalla_build_tiles` was handed - rather than from a
    constant here. `mjolnir.graph_lua_name` in that file is the instruction
    Valhalla was given, so this asks the only question worth asking: did the
    build load the script its own config named. A second copy of the path in
    this module would be the copy that goes stale, and the failure it would
    hide is precise - a generator retargeted at another script would produce
    builds that loaded exactly what they were told to and failed validation
    against a path nothing had used since.
    """
    config = json.loads(Path(build_config).read_text())
    expected = config.get("mjolnir", {}).get("graph_lua_name")
    if not expected:
        raise ValidationFailed(
            f"the {where} build config {build_config} names no mjolnir.graph_lua_name, so "
            "the build was never told which transform to load and nothing can say whether "
            "it loaded the right one"
        )
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
ADMIN_AND_TIMEZONE_TABLES = {"admin": "admins", "timezone": tiles.TIMEZONE_TABLE}


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


# The long trails' sentinel (operations review SF-1 of ZOOMED-TRAILS): each way in
# `settings.REBUILD_SENTINEL_LONG_TRAIL_WAYS` must come out on a long bicycle route
# in a named run of at least this much (8 mi, the z10 unpaved bar), and the table
# must hold at least `settings.REBUILD_LONG_TRAIL_FLOORS` rows on a long route and
# in a run of LONG_TRAIL_FLOOR_RUN_M (the z11 paved bar, 2.5 mi).
LONG_TRAIL_SENTINEL_ROUTE = ROUTE_LONG_BICYCLE
LONG_TRAIL_SENTINEL_RUN_M = round(Z10_UNPAVED_RUN_MI * METRES_PER_MILE)
LONG_TRAIL_FLOOR_RUN_M = round(Z11_PAVED_RUN_MI * METRES_PER_MILE)


# The ride layer's sentinel and floors (OWNER-DECISIONS 391, 402a; the same idea as the
# long trails'): the path sentinels (the W&OD and the C&O, which are long trails too) must
# come out in a connected network or run of at least LONG_TRAIL_SENTINEL_RUN_M, the road
# sentinel in a calm run of at least the road bar, and the table must hold at least
# `settings.REBUILD_CALM_RUN_FLOORS` path rows in a run of the path bar and road rows in a
# calm run of the road bar.
CALM_PATH_RUN_M = round(RIDE_PATH_RUN_MI * METRES_PER_MILE)
CALM_ROAD_RUN_M = round(RIDE_ROAD_RUN_MI * METRES_PER_MILE)


def assert_calm_runs(
    summary,
    path_sentinels: Sequence[int],
    street_sentinels: Sequence[int],
    floors: Sequence[int],
) -> None:
    """The z12-13 "where to ride" layer's runs came out of the rebuild: `calm_run_m`
    is written by this rebuild alone and the tiles filter on it silently, so a pass
    that lost the names or the geometry would promote a z12-13 map holding nothing
    but the roads closed to cars."""
    if summary.unset_named:
        raise ValidationFailed(
            f"{summary.unset_named} named ride-layer candidates are still at calm_run_m 0: "
            "the calm-run derive did not run to the end"
        )
    wanted = [(way, LONG_TRAIL_SENTINEL_RUN_M, "path") for way in path_sentinels]
    wanted += [(way, CALM_ROAD_RUN_M, "road") for way in street_sentinels]
    for way, minimum, kind in wanted:
        if way not in summary.sentinels:
            raise ValidationFailed(
                f"the calm-run {kind} sentinel way {way} is not in the segment table; if the "
                "extract split or replaced it, move the sentinel "
                "(settings.REBUILD_SENTINEL_CALM_PATH_WAYS or _STREET_WAYS), don't drop it"
            )
        if summary.sentinels[way] < minimum:
            raise ValidationFailed(
                f"the calm-run {kind} sentinel way {way} came out at a run of "
                f"{summary.sentinels[way]} m, not {minimum} m or more: the names or the "
                "geometry were lost, and z12-13 would drop the long paths and calm roads"
            )
    path_floor, street_floor = floors
    if summary.path_rows < path_floor or summary.street_rows < street_floor:
        raise ValidationFailed(
            f"{summary.path_rows} path rows are in a run of {CALM_PATH_RUN_M} m or more and "
            f"{summary.street_rows} road rows in a calm run of {CALM_ROAD_RUN_M} m or more, under "
            f"the floors of {path_floor} and {street_floor} (settings.REBUILD_CALM_RUN_FLOORS): "
            "the ride layer did not come out of the rebuild"
        )


def assert_long_trails(summary, sentinel_ways: Sequence[int], floors: Sequence[int]) -> None:
    """The zoomed-out map's long trails came out of the rebuild (OWNER-DECISIONS
    375): the columns are written by this rebuild alone and the tiles filter on
    them silently, so a pass that lost the route relations or the names would
    promote a z10-11 map holding little but the car-free roads."""
    if summary.unjudged_bridges:
        raise ValidationFailed(
            f"{summary.unjudged_bridges} bridge candidates are still at trail_bridge 3: "
            "the bridge judging did not run to the end"
        )
    for way in sentinel_ways:
        if way not in summary.sentinels:
            raise ValidationFailed(
                f"the long-trail sentinel way {way} is not in the segment table; if the "
                "extract split or replaced it, move the sentinel "
                "(settings.REBUILD_SENTINEL_LONG_TRAIL_WAYS), don't drop it"
            )
        route, run = summary.sentinels[way]
        if route < LONG_TRAIL_SENTINEL_ROUTE or run < LONG_TRAIL_SENTINEL_RUN_M:
            raise ValidationFailed(
                f"the long-trail sentinel way {way} came out at route level {route} and a "
                f"run of {run} m, not a long bicycle route ({LONG_TRAIL_SENTINEL_ROUTE}) in a "
                f"run of {LONG_TRAIL_SENTINEL_RUN_M} m or more: the route relations or the "
                "names were lost, and z10-11 would drop the long trails"
            )
    route_floor, run_floor = floors
    if summary.on_long_route < route_floor or summary.in_long_run < run_floor:
        raise ValidationFailed(
            f"{summary.on_long_route} rows are on a long route and {summary.in_long_run} in "
            f"a run of {LONG_TRAIL_FLOOR_RUN_M} m or more, under the floors of {route_floor} "
            f"and {run_floor} (settings.REBUILD_LONG_TRAIL_FLOORS): the long trails did not "
            "come out of the rebuild"
        )


def is_rated_osm_closure(tags: dict[str, str]) -> bool:
    """A way OSM itself closes to bicycles that carries an `mtb:*` rating, read
    narrowly enough that upstream's transform certainly keeps it closed.

    The ratings are what the parser reopened such a way from. `bicycle=no` with
    `foot` not `no` (a `foot=no` way nothing else may use is dropped outright,
    so it has no edge to read), and none of the keys upstream lets open a
    direction over `bicycle=no`.
    """
    if tags.get("bicycle") != "no" or tags.get("foot") == "no":
        return False
    if not any(key.startswith("mtb:") for key in tags):
        return False
    if any(key in tags for key in _OPENS_OVER_BICYCLE_NO):
        return False
    if tags.get("service") == "driveway":
        return False
    return not any(key.startswith("cycleway") for key in tags)


def probe_point(coordinates: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """The midpoint of a way's longest segment: on the way's own line, and as
    far from its end nodes, where other ways' edges meet it, as it can be."""
    best: tuple[float, tuple[float, float]] | None = None
    for (lon1, lat1), (lon2, lat2) in itertools.pairwise(coordinates):
        length = (lon2 - lon1) ** 2 + (lat2 - lat1) ** 2
        if length > 0 and (best is None or length > best[0]):
            best = (length, ((lon1 + lon2) / 2, (lat1 + lat2) / 2))
    return None if best is None else best[1]


def _spread(ids, limit: int) -> list[int]:
    """At most `limit` of `ids`, evenly spaced through them in id order, so the
    sample is the same for the same extract and reaches across the region."""
    ordered = sorted(ids)
    if len(ordered) <= limit:
        return ordered
    step = len(ordered) / limit
    return [ordered[int(index * step)] for index in range(limit)]


def closure_probes(context: RebuildContext) -> list[tiles.ClosureProbe]:
    """The gate's sample: singletrack (the rule's own ways) and rated OSM
    closures, each bounded, each with a point on its own line."""
    reference = context.require_reference()
    by_id = context.ways_by_id or {way.osm_id: way for way in context.ways}

    def walkable(osm_id: int) -> bool:
        way = by_id.get(osm_id)
        return way is not None and way.tags.get("foot") != "no"

    singles = [osm_id for osm_id in context.singletracks if walkable(osm_id)]
    osm = [
        way.osm_id
        for way in context.ways
        if way.osm_id not in context.singletracks
        and way.osm_id not in reference.bridge_bicycle_legal
        and is_rated_osm_closure(way.tags)
    ]
    probes = []
    single_ids = _spread(singles, CLOSURE_GATE_SINGLETRACKS)
    chosen = single_ids + _spread(osm, CLOSURE_GATE_OSM_CLOSURES)
    reasons = {osm_id: singletrack.NO_BICYCLE for osm_id in single_ids}
    # The new rules' ways, by reason: walkable, and not a bridge a fixture opens.
    by_reason: dict[str, list[int]] = {}
    no_bicycle = getattr(context, "no_bicycle", None) or {}
    destination_only = getattr(context, "destination_only", None) or set()
    for osm_id, reason in no_bicycle.items():
        if reason in (singletrack.NO_BICYCLE, cbd.NO_BICYCLE) or osm_id in chosen:
            continue
        if osm_id in reference.bridge_bicycle_legal or osm_id in destination_only:
            continue
        if walkable(osm_id):
            by_reason.setdefault(reason, []).append(osm_id)
    for reason, ids in sorted(by_reason.items()):
        for osm_id in _spread(ids, CLOSURE_GATE_PER_REASON):
            chosen.append(osm_id)
            reasons[osm_id] = reason
    for osm_id in chosen:
        point = probe_point(by_id[osm_id].coordinates)
        if point is not None:
            probes.append(tiles.ClosureProbe(osm_id, point[0], point[1], reasons.get(osm_id, "")))
    return probes


def write_closure_reports(out_dir: Path, probes, singletracks) -> None:
    """What the post-swap probe reads (scripts/probe_bicycle_closures.py)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / CLOSURE_PROBES_REPORT).write_text(
        "way_id,lon,lat,reason\n"
        + "".join(f"{p.way_id},{p.lon:.7f},{p.lat:.7f},{p.reason}\n" for p in probes)
    )
    (out_dir / SINGLETRACK_REPORT).write_text("".join(f"{w}\n" for w in sorted(singletracks)))


def assert_bicycle_closures_reached_the_tiles(readbacks: dict) -> None:
    """No staged graph may leave a sampled closure open to bicycles.

    And each graph that keeps trails must have found some of them: a read that
    finds no edge for any probe passes vacuously, which is what a locate in the
    wrong place or a changed response would look like. The no-trail graph drops
    every trail-class way, singletrack included, so it is held to the first
    rule only.
    """
    missing = [v.value for v in variants.Variant if v not in readbacks]
    if missing:
        raise ValidationFailed(
            f"no bicycle-closure read-back for {', '.join(missing)}, so nothing says "
            "those graphs keep singletrack closed"
        )
    for variant, readback in readbacks.items():
        if readback.open_to_bicycles:
            shown = ", ".join(str(w) for w in readback.open_to_bicycles[:REPORTED_VIOLATIONS])
            raise ValidationFailed(
                f"the {variant.value} graph is open to bicycles on "
                f"{len(readback.open_to_bicycles)} of {readback.probed} ways it must keep "
                f"closed (singletrack or OSM's own bicycle=no), e.g. way {shown}: "
                "something reopened them after the transform, as Valhalla's parser did "
                "from their mtb:* ratings (lua/graph.lua, remap.strip_ratings_if_closed)"
            )
        if variant is not variants.Variant.NO_TRAIL and readback.probed and not readback.found:
            raise ValidationFailed(
                f"the {variant.value} graph has no edge on any of the {readback.probed} "
                "bicycle-closure probes, so the read tested nothing"
            )
    logger.info(
        "bicycle closures held in every graph: %s",
        ", ".join(
            f"{variant.value} {readback.found}/{readback.probed} found"
            for variant, readback in readbacks.items()
        ),
    )


def assert_reference_lts4_street(
    context: RebuildContext,
    street: str,
    min_share: float,
    north_of_lat: float,
    north_min_share: float,
) -> lts_sentinels.StreetTiers | None:
    """The owner's reference LTS 4 road came out LTS 4 (OWNER-DECISIONS 408, 409;
    `pipeline.lts_sentinels`). Off with an empty street; skipped, with a warning, on a
    rebuild with no agency street layer installed (it classifies from OSM alone)."""
    if not street:
        return None
    reference = context.require_reference()
    if not reference.road_blocks:
        logger.warning(
            "no agency street layer is installed, so the reference LTS 4 road (%s) is not checked",
            street,
        )
        return None
    ids = lts_sentinels.block_ids(reference.road_blocks, street)
    if not ids:
        raise ValidationFailed(
            f"the installed Roadway Block has no block named {street}, so the owner's "
            "reference LTS 4 road (OWNER-DECISIONS 408) cannot be checked"
        )
    tiers = lts_sentinels.street_tiers(context.staging_schema, street, ids, north_of_lat)
    found = lts_sentinels.problems(tiers, min_share, north_min_share)
    if found:
        raise ValidationFailed("; ".join(found))
    logger.info(
        "%s: %.0f%% LTS 4, %.0f%% north of %.4f N",
        street,
        100 * tiers.share,
        100 * tiers.north_share,
        north_of_lat,
    )
    return tiers


def military_through_networks(
    context: RebuildContext, found: Sequence[restricted_areas.MilitaryWay] | None = None
) -> list[tuple[list[int], list[int]]]:
    """`restricted_areas.through_networks` over the rebuild's ways: the outside
    ways it needs are only those that share a node with an open in-base way.
    `found` is the military rule's ways (the default) or the secured compounds'
    (`context.secured_ways`); outside is outside both."""
    if found is None:
        found = context.military_ways
    inside = {m.way_id for m in context.military_ways} | {
        m.way_id for m in getattr(context, "secured_ways", None) or ()
    }
    open_in = {m.way_id for m in found if not m.closed}
    by_id = context.ways_by_id or {way.osm_id: way for way in context.ways}
    open_nodes = {node for way_id in open_in for node in getattr(by_id.get(way_id), "node_ids", ())}
    node_ids = {}
    outside_open = set()
    for way in context.ways:
        if way.osm_id in open_in:
            node_ids[way.osm_id] = way.node_ids
        elif (
            way.osm_id not in inside
            and way.node_ids
            and not open_nodes.isdisjoint(way.node_ids)
            and restricted_areas.open_to_bicycles(way.tags)
        ):
            node_ids[way.osm_id] = way.node_ids
            outside_open.add(way.osm_id)
    return restricted_areas.through_networks(found, node_ids, outside_open)


def assert_military_closures(
    context: RebuildContext,
    sentinel_ways: Sequence[int],
    min_closed: Mapping[str, int] | None = None,
) -> int:
    """Ways inside a military area were closed (owner report 2026-10-05): each
    sentinel way, a Joint Base Anacostia-Bolling walkway or service road with no
    access tag of its own, carries `rm:no_bicycle=military` where the extract has
    it. A sentinel the extract no longer has is warned about, not refused (OSM
    renumbers ways); the closure gate reads a sample of the reason's ways back
    from every graph. Returns the number of ways closed."""
    closed = sum(1 for m in context.military_ways if m.closed)
    by_site = Counter(m.installation for m in context.military_ways if m.closed)
    # A floor's key is one installation's OSM name, or a tuple of names counted
    # together: overlapping outlines (Bolling's old outline inside JBAB) split their
    # ways by which area holds most of each, and that tie-break can move with any
    # OSM edit, so only their sum is held.
    short = {}
    for site, floor in (min_closed or {}).items():
        names = (site,) if isinstance(site, str) else tuple(site)
        count = sum(by_site.get(name, 0) for name in names)
        if count < floor:
            short[site] = (count, floor)
    if short:
        raise ValidationFailed(
            "military areas closed fewer ways than their floor (closed, floor): "
            f"{short}; an installation's outline was lost or renamed upstream, so its "
            "roads and paths could be routed again (OWNER-DECISIONS 437; "
            "REBUILD_SENTINEL_MILITARY_MIN_CLOSED)"
        )
    if context.military_through:
        named = [
            (ways[:5], len(ways), len(entries)) for ways, entries in context.military_through[:5]
        ]
        raise ValidationFailed(
            "open networks inside a military area meet the public network at two or more "
            f"points (first ways, ways, entries): {named}; a route could pass through a base "
            "(OWNER-DECISIONS 437)"
        )
    present = {way.osm_id for way in context.ways}
    wrong = [
        way_id
        for way_id in sentinel_ways
        if way_id in present
        and context.no_bicycle.get(way_id) != restricted_areas.MILITARY_NO_BICYCLE
    ]
    missing = [way_id for way_id in sentinel_ways if way_id not in present]
    if missing:
        logger.warning(
            "military-closure sentinel ways not in the extract (renumbered?): %s", missing
        )
    if wrong:
        raise ValidationFailed(
            f"ways {wrong} inside Joint Base Anacostia-Bolling are not closed to bicycles "
            "(rm:no_bicycle=military): the military-area rule did not run or lost its areas, "
            "so a route could run through a base again (owner report 2026-10-05)"
        )
    logger.info(
        "military areas: %d ways closed to bicycles, %d left open (military-closures.csv)",
        closed,
        len(context.military_ways) - closed,
    )
    return closed


def assert_secured_closures(
    context: RebuildContext,
    sentinel_ways: Sequence[int],
    min_closed: Mapping[str, int] | None = None,
) -> int:
    """Ways inside a secured federal compound were closed (owner report 2026-10-06):
    each sentinel way, a James J. Rowley Training Center road or path with no access
    tag of its own, carries `rm:no_bicycle=secured` where the extract has it; each
    floored compound (by its `SECURED_AREAS` name) closed at least its floor, so an
    outline deleted or renumbered upstream fails the build rather than reopening the
    compound; and no open network inside one meets the public network at two or
    more points. Returns the number of ways closed."""
    found = getattr(context, "secured_ways", None) or []
    closed = sum(1 for m in found if m.closed)
    by_site = Counter(m.installation for m in found if m.closed)
    short = {
        site: (by_site.get(site, 0), floor)
        for site, floor in (min_closed or {}).items()
        if by_site.get(site, 0) < floor
    }
    if short:
        missing = getattr(context, "secured_missing", None) or []
        raise ValidationFailed(
            "secured federal compounds closed fewer ways than their floor (closed, floor): "
            f"{short}; curated areas the extract no longer has: {missing or 'none'}. An "
            "outline was lost, renumbered or renamed upstream, so its roads and paths could "
            "be routed again (owner report 2026-10-06; restricted_areas.SECURED_AREAS, "
            "REBUILD_SENTINEL_SECURED_MIN_CLOSED)"
        )
    through = getattr(context, "secured_through", None) or []
    if through:
        named = [(ways[:5], len(ways), len(entries)) for ways, entries in through[:5]]
        raise ValidationFailed(
            "open networks inside a secured federal compound meet the public network at two "
            f"or more points (first ways, ways, entries): {named}; a route could pass through "
            "one (owner report 2026-10-06)"
        )
    present = {way.osm_id for way in context.ways}
    wrong = [
        way_id
        for way_id in sentinel_ways
        if way_id in present
        and context.no_bicycle.get(way_id) != restricted_areas.SECURED_NO_BICYCLE
    ]
    missing_ways = [way_id for way_id in sentinel_ways if way_id not in present]
    if missing_ways:
        logger.warning(
            "secured-closure sentinel ways not in the extract (renumbered?): %s", missing_ways
        )
    if wrong:
        raise ValidationFailed(
            f"ways {wrong} inside the James J. Rowley Training Center are not closed to "
            "bicycles (rm:no_bicycle=secured): the secured-compound rule did not run or lost "
            "its areas, so a route could run through the compound again (owner report "
            "2026-10-06)"
        )
    logger.info(
        "secured federal compounds: %d ways closed to bicycles, %d left open "
        "(secured-closures.csv)",
        closed,
        len(found) - closed,
    )
    return closed


def assert_owner_stretches(context: RebuildContext, rows: Sequence) -> list:
    """Each owner-rated stretch (`REBUILD_SENTINEL_STRETCHES`; OWNER-DECISIONS 432) came
    out at the owner's tier. Off with no rows; skipped, with a warning, with no agency
    street layer installed, as the reference LTS 4 road is."""
    stretches = [lts_sentinels.Stretch.of(row) for row in rows]
    if not stretches:
        return []
    reference = context.require_reference()
    if not reference.road_blocks:
        logger.warning(
            "no agency street layer is installed, so the owner's stretches are not checked"
        )
        return []
    found, read = [], []
    for stretch in stretches:
        ids = lts_sentinels.block_ids(reference.road_blocks, stretch.street)
        if not ids:
            found.append(
                f"the installed Roadway Block has no block named {stretch.street}, so "
                f"{stretch.decision} cannot be checked"
            )
            continue
        tiers = lts_sentinels.stretch_tiers(context.staging_schema, stretch, ids)
        read.append(tiers)
        found.extend(lts_sentinels.stretch_problems(tiers))
        logger.info(
            "%s %.4f-%.4f N: %.0f%% at tier %d (%s)",
            stretch.street,
            stretch.south_lat,
            stretch.north_lat,
            100 * tiers.share,
            stretch.tier,
            stretch.decision,
        )
    if found:
        raise ValidationFailed("; ".join(found))
    return read


def assert_mass_capacity(
    summary, min_share: float | None = None, median_range: Sequence[float] | None = None
) -> None:
    """The Mass Ride capacity column came out of the rebuild (OWNER-DECISIONS 325-327,
    387): present on nearly every road and path row, in a plausible range
    (`pipeline.mass_capacity`). The map colours by it and falls back silently
    without it, so a pass that lost it would promote the old map unannounced."""
    found = mass_capacity.problems(
        summary,
        mass_capacity.MIN_SHARE if min_share is None else min_share,
        tuple(mass_capacity.MEDIAN_RANGE_RPM if median_range is None else median_range),
    )
    if found:
        raise ValidationFailed("; ".join(found))


def car_free_tier_1(way, stress_by_way: dict) -> bool:
    """Make a road closed to motor traffic for good tier 1, as the weekend graph
    makes a weekend closure; True when it did.

    PLAN:354: "A road closed to motor vehicles outright is a path", and a path
    carries no motor traffic to be stressed by. The classifier rates the road
    from its class and speed as though cars used it (Beach Drive NW, corrected
    car-free by the owner, came out tier 3), so the segment table reported the
    road as LTS 3 and the transform put the stress penalty on it. Replaced
    after the overrides (an approved `motor_vehicle=no` row counts), and only
    where no curated stress row set the tier: the owner's word on a way wins.
    """
    from routemaker.classes import TRAIL_CLASS_HIGHWAY
    from routemaker.stress import MOTOR_RESTRICTED_RULE, Stress, StressResult

    if way.tags.get("highway") in TRAIL_CLASS_HIGHWAY:
        return False
    # A road (not a trail, not a motor-only class) the facility rule reads as
    # an off-road path because it is closed to motor traffic.
    if facility.facility(way.tags) is not facility.Facility.PATH:
        return False
    current = stress_by_way.get(way.osm_id)
    if current is None or getattr(current, "adjustment", None) is not None:
        return False
    # Already tier 1 by the classifier's own reading, nothing to correct; but a tier 1
    # the motor-restriction cap set (OWNER-DECISIONS 444) is this rule's case, and gets
    # its reason and its count.
    if current.tier is Stress.LTS1 and not current.rule.startswith(MOTOR_RESTRICTED_RULE):
        return False
    stress_by_way[way.osm_id] = StressResult(
        tier=Stress.LTS1,
        rule=f"closed to motor traffic: an off-road path (was: {current.rule})",
        assumed=current.assumed,
        volume_source=current.volume_source,
        volume_aadt=current.volume_aadt,
        volume_year=current.volume_year,
        attr_sources=current.attr_sources,
        speed_mph=current.speed_mph,
        lanes=current.lanes,
        oneway=current.oneway,
        graph_oneway=current.graph_oneway,
    )
    return True


def facility_derived(
    variant: variants.Variant,
    way_id: int,
    facility_by_way: dict[int, str],
    car_free_by_way: dict[int, frozenset[str]],
) -> dict[str, object]:
    """The facility values one variant's extract hands the transform for a way.

    - No-trail, Mass Ride's graph: the neutral marker and no class, since no
      facility makes a street cheaper for it (the owner, 2026-09-27: "Mass
      rides don't need to consider these. Even protected bike lanes aren't
      used.").
    - Weekend: a road closed to motor traffic for the whole weekend
      (`ridetime.closed_settings`) is on this graph what a road closed for good
      is on every graph - an off-road path, at the lowest tier, so the stress
      penalty does not land on it either. Every other way as on the standard.
    - Standard and e-bike: the way's class.
    """
    if variant is variants.Variant.NO_TRAIL:
        return {"facility_neutral": True}
    if variant is variants.Variant.WEEKEND and ridetime.WEEKEND in car_free_by_way.get(way_id, ()):
        return {"facility": facility.Facility.PATH.value, "stress_tier": 1}
    if way_id in facility_by_way:
        return {"facility": facility_by_way[way_id]}
    return {}


def build_handlers(
    context: RebuildContext,
    run: Callable[[Sequence[str]], str] | None = None,
    sample_grade: Callable[[], float] | None = None,
    sample_derived_tag: Callable[[], str | None] | None = None,
    state_at: Callable[[float, float], str | None] | None = None,
    sample_weekend_tag: Callable[[], str | None] | None = None,
    load_overrides: Callable[[], list[overrides.Override]] | None = None,
    disk_usage: Callable | None = None,
    fetch_elevation: Callable[[elevation.TileName, Path], Path] | None = None,
    sample_closures: Callable[[], dict] | None = None,
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
    # The closure gate's reads carry their own timeout on top of the deadline,
    # so a wedged read fails VALIDATE_TILES in minutes rather than at hour eight. Its
    # timeout is marked as not the budget's (`_run_command`), so the 459a progress
    # retry does not take it for an attempt that ran out of time.
    closure_run = run or functools.partial(
        _run_command, deadline=context.deadline, timeout=CLOSURE_GATE_READ_TIMEOUT_S
    )
    run = run or functools.partial(_run_command, deadline=context.deadline)
    state_at = state_at or _state_at
    load_overrides = load_overrides or overrides.load_approved
    disk_usage = disk_usage or tiles.shutil.disk_usage
    fetch_elevation = fetch_elevation or elevation.fetch_3dep
    sample_grade = sample_grade or (lambda: _least_grade_across_variants(context, run))
    sample_derived_tag = sample_derived_tag or (lambda: _standard_cycle_lane(context, run))
    sample_weekend_tag = sample_weekend_tag or (lambda: _weekend_cycle_lane(context, run))
    sample_closures = sample_closures or (lambda: _closures_across_variants(context, closure_run))

    def classification_value(name: str):
        """A classification-affecting setting as this attempt will use it: the
        context's own value where the context carries one (a test or a second
        deployment may point it elsewhere), else the setting."""
        if name == "COVERAGE_BBOX":
            return list(context.coverage_bbox)
        if name == "COVERAGE_POLYGON":
            return None if context.coverage_polygon is None else str(context.coverage_polygon)
        if name == "SEGMENT_SCHEMA_STAGING":
            return context.staging_schema
        if name == "REBUILD_CROSSINGS_FIXTURE":
            return (
                None if context.checked_in_crossings is None else str(context.checked_in_crossings)
            )
        return _setting(name)

    def bookkeeping_failed(what: str) -> None:
        """Checkpoints are best effort: an error while measuring or writing one is
        logged, and the attempt carries on with them off. Writing no checkpoint is
        always safe; failing a rebuild that would have promoted is not. (The guards,
        `checkpoint.CheckpointRefused`, are not bookkeeping and still raise.)"""
        logger.exception(
            "checkpoint bookkeeping failed while %s; this attempt goes on and writes no "
            "further checkpoint",
            what,
        )
        context.checkpoints = False

    def measure_fingerprint(merged_pbf: Path) -> dict:
        """Every input the classification depends on, measured now."""
        return checkpoint.measure_classification_fingerprint(
            source_pbf=context.source_pbf,
            merged_pbf=merged_pbf,
            code_roots=context.code_roots,
            reference_dir=context.reference_dir,
            crossings_fixture=context.checked_in_crossings,
            coverage_polygon=context.coverage_polygon,
            classification_settings={
                name: classification_value(name)
                for name in checkpoint.SETTINGS_OF_KIND[checkpoint.CLASSIFICATION]
            },
            validation_settings={
                name: _setting(name) for name in checkpoint.SETTINGS_OF_KIND[checkpoint.VALIDATION]
            },
            override_rows=checkpoint.approved_override_rows(),
            jurisdictions=checkpoint.jurisdiction_digest(),
            smooth_volume=context.smooth_volume,
            hasher=context.hasher,
        )

    def resume_classification() -> bool:
        """Adopt the classification checkpoint if every part of it still holds.

        The checks are `checkpoint.classification_problem`'s, cheapest first. A
        failure deletes the manifest (first, before anything else is touched) and
        takes the fresh path under a new build id: the old id's directories are
        pruned at the end of the run like any failed attempt's.
        """
        manifest, context.resume = context.resume, None
        merged = context.source_pbf.parent / source.MERGED_NAME
        if not (context.source_pbf.is_file() and merged.is_file()):
            problem, validation_changed = "the source or merged extract is missing", False
        else:
            try:
                problem, validation_changed = checkpoint.classification_problem(
                    manifest,
                    job_id=context.job_id,
                    tiles_dir=context.tiles_dir,
                    measure_fingerprint=lambda: measure_fingerprint(merged),
                    variant_pbfs={v: context.variant_pbf(v) for v in variants.Variant},
                    hasher=context.hasher,
                )
            except checkpoint.CheckpointRefused:
                raise
            except Exception as error:  # noqa: BLE001 - not usable means start fresh
                logger.exception("could not check the classification checkpoint")
                problem = f"it could not be checked ({type(error).__name__}: {error})"
                validation_changed = False
        if problem is not None:
            logger.warning("not resuming the classification checkpoint: %s", problem)
            context.resume_note = f"fresh start: the checkpoint was not used ({problem})"
            context.resume_refused = True
            checkpoint.discard_classification(context.work_dir)
            remove_abandoned_build(manifest.get("build_id"))
            context.build_id = new_build_id(tiles_dir=context.tiles_dir)
            return False
        # The gate, sized for what is left to do: the variant extracts are on disk
        # already (and counted in what the volume uses), and so are the graphs this
        # job finished, so a resume needs the room of the graphs still to build and
        # scratch. Sizing it as a fresh run would refuse - terminally - the resume
        # that needs one graph's room on exactly the volume that is tight.
        to_build = [
            variant
            for variant in variants.Variant
            if not finished_graph(variant, manifest["build_id"])
        ]
        context.disk_gate = tiles.check_resume_disk_gate(
            context.tiles_dir,
            to_build,
            context.source_pbf.stat().st_size,
            _setting("REBUILD_MIN_FREE_BYTES"),
            _setting("DISK_GATE_FRACTION"),
            disk_usage=disk_usage,
        )
        context.build_id = manifest["build_id"]
        context.resumed_build_id = manifest["build_id"]
        context.merged_pbf = merged
        context.closure_probes = [
            tiles.ClosureProbe(
                int(entry["way_id"]), float(entry["lon"]), float(entry["lat"]), entry["reason"]
            )
            for entry in manifest.get("closure_probes", [])
        ]
        context.singletracks = {int(way_id) for way_id in manifest.get("singletracks", [])}
        context.override_summary = manifest.get("override_summary")
        context.resumed = True
        context.revalidate_staging = validation_changed
        context.resume_note = (
            f"resumed job {context.job_id} build {context.build_id}: classification from "
            f"{manifest.get('written_at')}"
        )
        logger.info("%s", context.resume_note)
        return True

    def finished_graph(variant: variants.Variant, build_id: str) -> bool:
        """Whether this job left a manifest for the variant's graph in `build_id` (read
        only, not re-hashed: that is BUILD_TILES's check). For sizing the gate."""
        found = checkpoint.read_json(
            checkpoint.graph_manifest_path(tiles.build_dir(context.tiles_dir, variant, build_id))
        )
        return (
            found is not None
            and found.get("job_id") == context.job_id
            and found.get("build_id") == build_id
        )

    def remove_abandoned_build(build_id) -> None:
        """A refused checkpoint's graphs are of no further use: delete them before
        the fresh disk gate counts them. Only an unpromoted build id is touched, and
        through the same guarded delete as a partial graph."""
        if (
            not isinstance(build_id, str)
            or not checkpoint.BUILD_ID.match(build_id)
            or build_id in checkpoint.promoted_build_ids(context.tiles_dir)
        ):
            return
        for variant in variants.Variant:
            try:
                checkpoint.remove_partial_graph(
                    context.tiles_dir, variant, build_id, this_build=build_id
                )
            except checkpoint.CheckpointRefused:
                raise
            except OSError:
                logger.warning(
                    "could not delete the abandoned %s graph of build %s",
                    variant.value,
                    build_id,
                    exc_info=True,
                )

    def fetch_extract() -> None:
        if context.resume is not None and resume_classification():
            return
        # The fresh path. The checkpoint is deleted first, before the extract can
        # be refreshed or the staging schema dropped: from here on it describes a
        # world that is about to change, and a manifest that outlived its schema
        # is the one thing the design must not leave.
        checkpoint.discard_classification(context.work_dir)
        fetch_fresh_extract()
        if context.checkpoints:
            try:
                context.start_fingerprint = measure_fingerprint(context.merged_pbf)
            except Exception:  # noqa: BLE001 - checkpoints are best effort
                bookkeeping_failed("measuring the inputs at the start")
        reset_and_read()

    def fetch_fresh_extract() -> None:
        """Produce this week's extract, or reuse the one on disk.

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
        # reserves the source size once per variant extract (four) and once more
        # for scratch, which covers the production's files as well.
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

    def reset_and_read() -> None:
        # The staging schema is rebuilt from scratch every week, and it is reset
        # here rather than by the segment writer because the crossings are
        # written into it several stages before the segments are.
        from .schema import reset_segment_schema

        writers.refuse_live_schema(context.staging_schema)
        reset_segment_schema(context.staging_schema)

        context.ways = extract.read_ways(context.source_pbf)
        # The OSM route relations the ways are in, for the zoomed-out long trails
        # (OWNER-DECISIONS 375).
        routes = trail_routes.read_routes(context.source_pbf)
        context.trail_routes = routes.levels
        context.mountain_bike_ways = routes.mountain_bike
        context.route_names = routes.names
        # Indexed once. The first version scanned the whole way list inside a
        # loop over every border node inside a loop over every variant.
        context.ways_by_id = {way.osm_id: way for way in context.ways}

    def load_reference_data() -> None:
        # Given the ways, because the crossings fixture resolves by name against
        # the extract. FETCH_EXTRACT runs first for exactly this reason.
        context.reference = ReferenceData.load(
            context.reference_dir,
            context.ways,
            checked_in_crossings=context.checked_in_crossings,
        )

    def ensure_elevation() -> None:
        # Cached across rebuilds and re-validated on each: a truncated tile
        # reads as flat terrain rather than as an error, and the build stage
        # reads whatever is in this directory without complaint.
        context.elevation_tiles = elevation.ensure_tiles(
            context.elevation_dir, context.coverage_bbox, fetch_elevation, run
        )

    def conflate_road_blocks(entries: list) -> None:
        """Match the agency street blocks to the ways that lie along them."""
        reference = context.require_reference()
        if not reference.road_blocks:
            return
        # The owner's corrections to a block's record (OWNER-DECISIONS 197), by
        # the layer's own key; one that names no installed block withholds
        # nothing, and the agency's value is read against the owner's decision.
        withheld = agency_roads.resolve_withheld(
            agency_roads.withheld_blocks(),
            ((block.feature_id, block.facts) for block in reference.road_blocks),
        )
        for unmatched in withheld.unmatched:
            logger.warning(
                "owner's block correction not applied (fixtures/overrides agency_blocks): %s; "
                "reinstall the street blocks (scripts/install_reference_data.py "
                "--roadway-block) or correct the override file",
                unmatched,
            )
        by_way, result = conflation.road_facts_by_way(
            context.ways, entries, reference.road_blocks, withheld=withheld.by_block
        )
        tags_of = {way.osm_id: way.tags for way in context.ways if way.osm_id in by_way}
        counted = set(context.aadt_by_way)
        for way_id, facts in by_way.items():
            match = conflation.block_count(way_id, tags_of[way_id], facts, result, counted)
            if match is not None:
                context.aadt_by_way[way_id] = match
        context.road_facts_by_way = by_way
        per_agency = Counter(facts.agency for facts in by_way.values())
        logger.info(
            "agency street blocks: %d of %d blocks matched ways (%s), %d ways matched",
            len(reference.road_blocks) - len(result.unmatched_features),
            len(reference.road_blocks),
            ", ".join(f"{agency} {count}" for agency, count in sorted(per_agency.items())),
            len(by_way),
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
        entries = [
            (way.osm_id, way.coordinates, variants.is_trail_class(way.tags)) for way in context.ways
        ]
        result = conflation.conflate(entries, reference.volume_features)
        context.aadt_by_way = dict(result.matched)
        # The agency street blocks next: their count (DC's Roadway Block AADT,
        # 2020) fills where no count layer reached the way and never replaces
        # one - DDOT's own 2024 counts are the newer survey.
        conflate_road_blocks(entries)
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
        # Whose statutory speed default an unposted way takes (the District's
        # 20 mph, OWNER-DECISIONS 108): state polygons from this rebuild's own
        # merged extract (OWNER-DECISIONS 137), not the admin's jurisdiction
        # table, and a refusal when a required state is missing.
        try:
            polygons = states.state_polygons(context.merged_pbf or context.source_pbf)
            state_of = states.way_states(context.ways, polygons)
        except states.StatesMissing as missing:
            # Terminal, like a refused override: a fifth attempt reads the
            # same extract and finds the same boundaries.
            raise ValidationFailed(str(missing)) from missing
        # Each count the volume gates read is its street's median where the street
        # disagrees (OWNER-DECISIONS 285, 296), after the states are known
        # because a street is smoothed within its own jurisdiction.
        smoothed_rule: set[int] = set()
        if context.smooth_volume:
            context.aadt_raw_by_way = dict(context.aadt_by_way)
            context.aadt_by_way, context.smoothing_report = aadt_smoothing.smooth(
                context.ways, context.aadt_by_way, state_of.get
            )
            logger.info("%s", context.smoothing_report.summary())
            smoothed_rule = {
                item.way_id
                for item in context.smoothing_report.replaced
                if aadt_smoothing.crosses_volume_gate(item.raw, item.smoothed)
            }
        # One-way ways that are a carriageway of a divided road, which item
        # 109's one-way relief does not apply to.
        started = time.monotonic()
        divided_ways = divided.carriageways(context.ways)
        logger.info(
            "divided roads: %d carriageways in %.1f s",
            len(divided_ways),
            time.monotonic() - started,
        )
        # Roads whose bike facility is mapped as its own way and lies beside
        # them: bike infrastructure to the arterial floor (OWNER-DECISIONS 141).
        _trails, separate_roads = facility.separate_pairs(
            (way.osm_id, way.tags, way.coordinates) for way in context.ways
        )
        # The curated speed limits the map is missing (OWNER-DECISIONS 131),
        # read here because the tier is what they are for; a posted speed wins.
        speeds = speed_corrections.load()
        used: set[int] = set()
        # And the curated bike lanes (OWNER-DECISIONS 433, Veirs Mill Road): a painted
        # lane the map is missing, for the classifier and the facility class only.
        lanes = bike_lanes.load()
        laned: set[int] = set()
        # The agency's street layer, over the way's own tags: a posted speed,
        # lanes, one-way, bike lane and parking it records take precedence (in
        # the District over OSM's own tagging too, OWNER-DECISIONS 190), and the
        # curated speed below fills only what is still missing. A bike facility
        # OSM maps as its own way - this way's, or another way's on one of its
        # blocks - stays there, never written onto the road (reviews r1, r2).
        overlays = conflation.overlay_road_facts(
            context.ways, context.road_facts_by_way, divided_ways, separate_roads
        )
        precedence: Counter = Counter()
        # The District's matched ways, for the discrepancy report: (way, the
        # tags the classifier read, its count, its overlay).
        reported: list[tuple] = []
        for way in context.ways:
            match = context.aadt_by_way.get(way.osm_id)
            tags = way.tags
            facts = context.road_facts_by_way.get(way.osm_id)
            overlaid = overlays.get(way.osm_id)
            if facts is not None and overlaid is not None:
                precedence.update(overlaid.precedence)
                tags = overlaid.tags
                context.class_tags_by_way[way.osm_id] = tags
                # The direction the classifier reads is the graph's as well
                # (OWNER-DECISIONS 216), from the one decision.
                routed = variants.agency_routing_tags(way.tags, overlaid.routing)
                if routed:
                    context.routing_tags_by_way[way.osm_id] = routed
                # The count's source is the count the classifier reads below:
                # DDOT's or VDOT's where a count layer reached the way, the
                # block's only where none did.
                sources = {**overlaid.sources, "aadt": agency_roads.aadt_source(match)}
                context.road_attr_sources[way.osm_id] = (
                    *sorted(sources.items()),
                    *(("blocks", block) for block in facts.blocks[:MAX_RECORDED_BLOCKS]),
                )
                if overlaid.disagreements:
                    context.road_disagreements[way.osm_id] = overlaid.disagreements
            tags, applied = speed_corrections.corrected(tags, speeds.get(way.osm_id))
            if applied:
                used.add(way.osm_id)
            tags, lane_applied = bike_lanes.corrected(tags, lanes.get(way.osm_id))
            if lane_applied:
                laned.add(way.osm_id)
                context.class_tags_by_way[way.osm_id] = tags

            def classified(aadt, tags=tags, way=way, match=match, facts=facts):
                return classify(
                    tags,
                    aadt=aadt,
                    # The agency, not the precedence tier: the tier is what
                    # `conflate` ranked two counts with and says nothing about
                    # who published the winner.
                    aadt_source=match.agency if match else None,
                    aadt_year=match.year if match else None,
                    urban=way.osm_id in reference.urban_way_ids,
                    jurisdiction=state_of.get(way.osm_id),
                    divided=way.osm_id in divided_ways,
                    separate_facility=way.osm_id in separate_roads,
                    parking_width_m=facts.parking_reach_m if facts is not None else None,
                )

            context.stress_by_way[way.osm_id] = classified(match.aadt if match else None)
            if match is not None and match.raw_aadt is not None:
                # Smoothed (OWNER-DECISIONS 285, 303): the link is classified on
                # the street's median, but the segment publishes what the agency
                # counted, and the tier on that count is kept for the junction
                # model, which charges the volume bunched at the intersection
                # (ARTERIAL review r0, SF1).
                unsmoothed = classified(match.raw_aadt)
                current = context.stress_by_way[way.osm_id]
                context.stress_by_way[way.osm_id] = replace(
                    current,
                    volume_aadt=match.raw_aadt,
                    unsmoothed_tier=unsmoothed.tier if unsmoothed.tier > current.tier else None,
                    rule=current.rule
                    + (", street volume (median)" if way.osm_id in smoothed_rule else ""),
                )
            if lane_applied:
                # The owner's reading of the curated lane (433, 437.4): LTS 4 on three
                # or more lanes a direction or at 45 mph and more.
                context.stress_by_way[way.osm_id] = bike_lanes.owner_tier(
                    context.stress_by_way[way.osm_id], tags
                )
            if overlaid is not None:
                context.stress_by_way[way.osm_id] = replace(
                    context.stress_by_way[way.osm_id],
                    attr_sources=context.road_attr_sources[way.osm_id],
                )
                if facts.agency == agency_roads.DC_AGENCY and state_of.get(way.osm_id) == "DC":
                    reported.append((way, tags, match, overlaid))
        if context.road_facts_by_way:
            # Where an agency's record and the way's own tags disagree and the way
            # was left alone (an OSM lane the agency does not record; an OSM
            # one-way on a block the agency calls two-way): counted, for the
            # report, not decided here.
            kinds = Counter(kind for found in context.road_disagreements.values() for kind in found)
            logger.info(
                "agency street blocks classified %d ways; where they disagree with the way's "
                "own tags and it was left alone: %s; where the District's record overrode "
                "OSM's tag (OWNER-DECISIONS 190 rows): %s; ways whose routing direction the "
                "record set (OWNER-DECISIONS 216): %d",
                len(context.road_facts_by_way),
                dict(sorted(kinds.items())) or "none",
                dict(sorted(precedence.items())) or "none",
                len(context.routing_tags_by_way),
            )
        if reported:
            write_discrepancy_report(reported, speeds, divided_ways, separate_roads, state_of)
        # The owner's named corridors (OWNER-DECISIONS 286, 294-296), over the
        # classified tiers and under the override rows. A way's recorded bike
        # lane (the agency overlay) exempts it, as an OSM one does.
        context.corridor_report = corridors.apply(
            corridors.load(),
            context.ways,
            context.stress_by_way,
            tags_of=context.class_tags_by_way,
            separate_roads=separate_roads,
        )
        logger.info("%s", context.corridor_report.summary())
        # Per way, beside the re-match report; with the veto the smoothing file
        # is header-only, so last week's list does not stand in for this one.
        write_reports(
            context.work_dir,
            {
                SMOOTHING_REPORT_NAME: (
                    context.smoothing_report or aadt_smoothing.SmoothingReport()
                ).to_csv(context.stress_by_way),
                CORRIDOR_REPORT_NAME: context.corridor_report.to_markdown(),
            },
            "AADT smoothing and named-corridor",
        )
        if context.corridor_report.unmatched_entries:
            logger.warning(
                "owner's named-corridor entries matched no way (fixtures/corridors): %s; the "
                "extract's geometry has moved, or the file is wrong",
                ", ".join(context.corridor_report.unmatched_entries),
            )
        context.speed_corrected = used
        unused = sorted(set(speeds) - used)
        if unused:
            # Posted since, or gone from the extract: either way the row is no
            # longer what sets the way's speed, which a reviewer should know.
            logger.warning("curated speed limits not applied (posted, or no such way): %s", unused)
        context.bike_lanes_marked = laned
        logger.info("curated bike lanes (fixtures/bike_lanes): %d ways", len(laned))
        unused_lanes = sorted(set(lanes) - laned)
        if unused_lanes:
            # Mapped since (the owner's OSM edit), or gone from the extract.
            logger.warning(
                "curated bike lanes not applied (a cycleway tag now, or no such way): %s",
                unused_lanes,
            )

    def write_discrepancy_report(reported, speeds, divided_ways, separate_roads, state_of) -> None:
        """The DC-against-OSM discrepancy report for the owner, each rebuild
        (OWNER-DECISIONS 191), from the overlay this rebuild classified with:
        `<DATA_ROOT>/rebuild/reports/dc-osm-discrepancies.md` and `.csv`. A
        report, not a stage's output: it never fails the rebuild. The tier with
        OSM's tags alone is the classifier's on the way's own tags with the count
        a count layer gave it (not a block's), as `data_before_after.py` has it."""
        reference = context.require_reference()
        try:
            rows = []
            for way, tags, match, overlaid in reported:
                counted = match if match is not None and match.source != "inventory" else None
                osm_tags, _ = speed_corrections.corrected(way.tags, speeds.get(way.osm_id))
                if way.tags.get("highway") in discrepancies.NOT_ROADS:
                    continue
                before = classify(
                    osm_tags,
                    aadt=counted.aadt if counted else None,
                    aadt_source=counted.agency if counted else None,
                    aadt_year=counted.year if counted else None,
                    urban=way.osm_id in reference.urban_way_ids,
                    jurisdiction=state_of.get(way.osm_id),
                    divided=way.osm_id in divided_ways,
                    separate_facility=way.osm_id in separate_roads,
                )
                facts = context.road_facts_by_way[way.osm_id]
                rows.append(
                    discrepancies.row(
                        way=way.osm_id,
                        name=way.tags.get("name"),
                        highway=way.tags.get("highway", ""),
                        length_m=conflation._length_m(way.coordinates),
                        blocks=facts.blocks,
                        tier0=int(before.tier),
                        tier1=int(context.stress_by_way[way.osm_id].tier),
                        disagreements=overlaid.disagreements,
                        agreements=overlaid.agreements,
                        osm=way.tags,
                        after=tags,
                        facts=discrepancies.facts_summary(facts),
                        sources={**overlaid.sources, "aadt": agency_roads.aadt_source(match)},
                    )
                )
            out_dir = context.work_dir / DISCREPANCY_REPORT_DIR
            found = discrepancies.write_report(rows, out_dir, discrepancies.REBUILD_SOURCE)
            logger.info(
                "DC-against-OSM discrepancy report: %d items on %d ways, written to %s",
                len(found),
                len(rows),
                out_dir,
            )
        except Exception:
            logger.warning("DC-against-OSM discrepancy report not written", exc_info=True)

    def tag_jurisdictions() -> None:
        """Annotate each way with the authorities its geometry falls under.

        In memory and no further, today. `_jurisdictions` is an underscore key,
        which is not an OSM key and must never be written into a PBF, so
        `inject_tags` filters the whole prefix out of the diff it writes; the
        tag transform therefore never sees it, and the segment table has no
        jurisdiction column for it either. Nothing downstream of this process
        can read what this stage computes.

        Kept, and kept here, because the assignment is the real work and the
        position is the one the override stage needs: `apply_jurisdiction` has
        to land after this and a consumer will read the same annotation. What
        is missing is that consumer - a column on the segment table, which the
        permit workflow reads without re-running a spatial query per route.
        Recorded in handoff.md section 7 against PLAN.md:28 and :151.
        """
        from django.contrib.gis.geos import LineString

        from .jurisdiction import assign_way, has_polygons

        # With no polygon loaded every way's answer is known before asking:
        # the empty assignment. A fresh deployment has none until an instance
        # admin enters them (PLAN.md phase 3 is the layer work), and the first
        # rebuild on a real host spent 35 minutes here on 1.3 million queries
        # that could only return nothing - and said nothing about why every
        # way came out with no authority.
        loaded = has_polygons()
        if not loaded:
            logger.warning(
                "no jurisdiction polygons are loaded, so every way is assigned no police, "
                "right-of-way or park authority; enter them in the admin's Jurisdiction page"
            )

        for way in context.ways:
            if len(way.coordinates) < 2:
                continue
            assignments = assign_way(LineString(way.coordinates, srid=4326)) if loaded else []
            # Assigned, not defaulted. `_jurisdictions` is this pipeline's own
            # key (`extract.INTERNAL_PREFIX`), and the only thing that can have
            # put one on a way before this stage runs is the source PBF: OSM
            # accepts any key, so a way tagged `_jurisdictions=...` upstream
            # would keep whatever string it carried and this stage's spatial
            # assignment would be discarded without a word. `apply_jurisdiction`
            # is the other writer and it runs after this stage, so it is not
            # what the guard was protecting.
            way.tags["_jurisdictions"] = ",".join(
                sorted(authorities_for(assignments, MIN_JURISDICTION_FRACTION))
            )

    def write_rematch_report(report) -> None:
        """`<DATA_ROOT>/rebuild/reports/override-rematch.md` and `.csv`: every
        override row whose way was missing, and what became of it. A report, not
        a stage's output: it never fails the rebuild."""
        write_reports(
            context.work_dir,
            {
                f"{REMATCH_REPORT_NAME}.md": report.to_markdown(),
                f"{REMATCH_REPORT_NAME}.csv": report.to_csv(),
            },
            "override re-match",
        )

    def apply_overrides() -> None:
        """The audited corrections, applied where each kind belongs.

        Until this stage existed the override table was one the admin could edit
        and no stage ever read: a row could be written, reviewed and approved,
        and the graph was built exactly as if it were not there.
        """
        rows = load_overrides()
        unhandled = sorted({row.kind for row in rows} - overrides.HANDLED_KINDS)
        if unhandled:
            # Refused rather than ignored, and terminal rather than retried: a
            # kind no applier handles is a row that was written, reviewed and
            # approved and then did nothing at all, which is the failure this
            # whole stage exists to end, and a fifth attempt applies it no more
            # than the first. The offending rows are named because the fix is to
            # the row or to the appliers, and neither is findable from the kind
            # alone.
            rows_named = ", ".join(
                f"{row.kind} on way {row.osm_way_id}"
                for row in rows
                if row.kind not in overrides.HANDLED_KINDS
            )
            raise ValidationFailed(
                f"approved override rows carry kinds no applier handles: {unhandled}; "
                f"the handled kinds are {sorted(overrides.HANDLED_KINDS)} ({rows_named})"
            )
        # A row whose way left the extract is re-pointed at the ways that now
        # stand for it, where that is unambiguous (OWNER-DECISIONS 282); every
        # row that was missing is in the report, and a failed one stays as it
        # was, so the appliers below still list its way as unmatched.
        started = time.monotonic()
        rows, rematch_report = rematch.resolve(rows, context.ways_by_id)
        logger.info("%s (%.1f s)", rematch_report.summary(), time.monotonic() - started)
        for entry in rematch_report.entries:
            level = logging.WARNING if entry.outcome in ("failed", "drifted") else logging.INFO
            logger.log(
                level,
                "override %s on way %s: %s %s %s",
                entry.kind,
                entry.old_way_id,
                entry.outcome,
                list(entry.new_way_ids) or "",
                entry.reason,
            )
        write_rematch_report(rematch_report)
        try:
            access, access_missing, superseding = overrides.apply_access(context.ways, rows)
            stress, stress_missing = overrides.apply_stress(context.stress_by_way, rows)
            jurisdiction, jurisdiction_missing = overrides.apply_jurisdiction(context.ways, rows)
        except overrides.OverrideRefused as refused:
            # The same door as the unhandled kind above and it has to close the
            # same way: an approved row asking for something an override may not
            # do - a write outside the access keys, an authority list with
            # nothing in it - is answered by editing the row, never by running
            # the rebuild again. `OverrideRefused` is a ValueError and nothing
            # made it terminal, so each one cost five full rebuilds before the
            # alert said anything an operator could act on.
            raise ValidationFailed(f"an approved override row was refused: {refused}") from refused

        missing = tuple(sorted({*access_missing, *stress_missing, *jurisdiction_missing}))
        if missing:
            # An approved correction that reaches nothing is a correction that is
            # not in force, which is worth an operator's attention rather than a
            # silent no-op.
            logger.warning("approved overrides matched no way in the extract: %s", missing)
        reference = context.reference
        # Only the ways the fixture actually has an opinion about: a bicycle key
        # written on any other way supersedes nothing, and counting it would
        # turn an ordinary access correction into a report that a checked-in row
        # had been overruled.
        superseded = {
            way_id: directions
            for way_id, directions in superseding.items()
            if reference is not None and way_id in reference.bridge_bicycle_legal
        }
        context.bicycle_override_directions = superseded
        context.bicycle_override_ways = frozenset(superseding)
        for way_id in sorted(superseded):
            way = context.ways_by_id.get(way_id)
            directions = superseded[way_id]
            if directions == overrides.BOTH_DIRECTIONS:
                logger.info(
                    "way %s (%s) carries an approved bicycle access override in both "
                    "directions, so the crossings fixture's roadway legality is withheld on it "
                    "and the reviewed value is what the graph carries",
                    way_id,
                    getattr(way, "name", None) or "unnamed",
                )
            else:
                (direction,) = directions
                logger.info(
                    "way %s (%s) carries an approved bicycle access override for the %s "
                    "direction only, so the reviewed value overrules the crossings fixture's "
                    "roadway legality that way and the fixture still decides the other",
                    way_id,
                    getattr(way, "name", None) or "unnamed",
                    direction,
                )
        context.override_report = overrides.OverrideReport(
            access=access,
            stress=stress,
            jurisdiction=jurisdiction,
            unmatched_way_ids=missing,
            fixture_rows_superseded=len(superseded),
            rematched=len(rematch_report.rematched),
            rematch_failed=len(rematch_report.failed),
            rematch_report=rematch_report,
        )
        logger.info("%s", context.override_report.summary())

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

    def classify_facilities() -> None:
        """Each way's facility class, once, from the tags the overrides left.

        After APPLY_OVERRIDES on purpose: whether a bicycle may ride a way is
        part of the class, and an approved access row is what corrects that.
        """
        if context.facility_by_way or not context.ways:
            return
        beside = facility.beside_separate_roads(
            (way.osm_id, way.tags, way.coordinates) for way in context.ways
        )
        context.short_paths_hidden = facility.short_paths_to_hide(
            (way.osm_id, way.tags, way.node_ids, way.coordinates) for way in context.ways
        )
        # By their place: the roads inside a military base, many with no access
        # tag of their own (the Pentagon's; OWNER-DECISIONS 88), every way inside
        # a cemetery (98), and a parking lot's own ways (99). Map only, but for
        # the cemeteries, which are also destination-only for routing.
        areas = restricted_areas.restricted_areas(context.source_pbf)
        placed = [(way.osm_id, way.tags, way.coordinates) for way in context.ways]
        context.cemetery_ways = restricted_areas.cemetery_ways(placed, areas["cemetery"])
        # And closed to bicycles, everything inside a military area (by the share of
        # its length) but a numbered public road, a way signed for bicycles, the
        # Pentagon's listed ways and what an owner's override reopens (owner report
        # 2026-10-05, "err closed on bike access", OWNER-DECISIONS 330, 437); what is
        # left open is drawn, and a closed road is left off the map (88).
        context.military_ways = restricted_areas.military_closures(
            placed, areas["military"], reopened=context.bicycle_override_ways
        )
        military_closed = {m.way_id for m in context.military_ways if m.closed}
        # And a secured federal compound's, by the same rule (owner report 2026-10-06:
        # the Secret Service's Rowley Training Center), but for the ways the military
        # rule already judged.
        context.secured_ways = restricted_areas.secured_closures(
            placed,
            areas[restricted_areas.SECURED],
            reopened=context.bicycle_override_ways,
            skip={m.way_id for m in context.military_ways},
        )
        secured_closed = {m.way_id for m in context.secured_ways if m.closed}
        context.secured_missing = restricted_areas.secured_missing(areas[restricted_areas.SECURED])
        if context.secured_missing:
            logger.warning(
                "secured compounds listed by OSM id (restricted_areas.SECURED_AREAS) not in "
                "the extract, so not closed (renumbered upstream?): %s",
                context.secured_missing,
            )
        context.short_paths_hidden |= {
            m.way_id
            for m in (*context.military_ways, *context.secured_ways)
            if m.closed and m.highway not in restricted_areas.TRAIL_CLASS_HIGHWAY
        }
        logger.info("%s", restricted_areas.military_summary(context.military_ways))
        logger.info(
            "%s",
            restricted_areas.military_summary(context.secured_ways, "secured federal compounds"),
        )
        missing_pentagon = restricted_areas.pentagon_open_missing(context.military_ways)
        if missing_pentagon:
            logger.warning(
                "Pentagon ways listed open (OWNER-DECISIONS 437.5) not found open in the "
                "reservation, so closed (renumbered upstream?): %s",
                missing_pentagon,
            )
        context.military_through = military_through_networks(context)
        context.secured_through = military_through_networks(context, context.secured_ways)
        # Paved ways with a mountain-bike rating: the remap removes the rating, which
        # Valhalla's parser would price as dirt (lua/routemaker_remap.lua,
        # strip_paved_ratings; the paved Rock Creek Trail in Montgomery County).
        # Paved is every hard surface, wooden bridges included (OWNER-DECISIONS 440).
        paved_rated = sum(
            1
            for way in context.ways
            if surfaces.is_paved(way.tags)
            and any(way.tags.get(key) is not None for key in singletrack.SCALE_KEYS)
        )
        logger.info(
            "paved ways with an mtb rating, priced paved in the graph (the remap drops the "
            "rating): %d",
            paved_rated,
        )
        write_reports(
            context.work_dir,
            {
                MILITARY_REPORT_NAME: restricted_areas.military_report_csv(context.military_ways),
                SECURED_REPORT_NAME: restricted_areas.military_report_csv(
                    context.secured_ways, "facility"
                ),
            },
            "military-closure",
        )
        context.short_paths_hidden |= context.cemetery_ways
        context.short_paths_hidden |= restricted_areas.parking_ways(placed, areas["parking"])
        routes = route_relations.read_routes(context.source_pbf)
        nobike = trail_closures.closures(
            context.ways,
            routes,
            areas[restricted_areas.PARK],
            military=military_closed,
            secured=secured_closed,
            reopened=context.bicycle_override_ways,
        )
        context.no_bicycle = nobike.reasons
        context.walk_bike = nobike.walk_bike
        context.destination_only = nobike.destination_only
        context.mtb_only = nobike.mtb_only()
        context.cbd_sidewalks = {w for w, r in nobike.reasons.items() if r == cbd.NO_BICYCLE}
        context.singletracks = {w for w, r in nobike.reasons.items() if r == singletrack.NO_BICYCLE}
        car_free_for_good = 0
        for way in context.ways:
            # The tags the classifier read where an agency's street layer
            # corrected them, so the facility the map draws is the facility the
            # tier was scored on.
            context.facility_by_way[way.osm_id] = facility.facility(
                context.class_tags_by_way.get(way.osm_id, way.tags),
                beside_separate_road=way.osm_id in beside,
            ).value
            closed = facility.car_free_when(way.tags)
            if closed:
                context.car_free_by_way[way.osm_id] = closed
            if nobike.reasons.get(way.osm_id) == trailaccess.MTB:
                # No path rail on a trail only a mountain bike rides.
                context.facility_by_way[way.osm_id] = facility.Facility.NONE.value
            if car_free_tier_1(way, context.stress_by_way):
                car_free_for_good += 1
        logger.info(
            "facility classes: %s; %d ways car-free at set times, %d car-free for good "
            "(tier 1), %d beside a road that maps its facility separately, %d CBD sidewalks "
            "barred to bicycles, %d singletrack ways avoided; no-bicycle reasons %s, %d "
            "walk-your-bike connectors kept, %d destination-only",
            dict(sorted(Counter(context.facility_by_way.values()).items())),
            len(context.car_free_by_way),
            car_free_for_good,
            len(beside),
            len(context.cbd_sidewalks),
            len(context.singletracks),
            dict(sorted(nobike.counts().items())),
            len(nobike.walk_bike),
            len(nobike.destination_only),
        )

    def routing_tags(way: extract.Way, variant: variants.Variant) -> dict[str, str]:
        """The way's tags for a variant to build from: its working tags
        (the source's, with the approved access overrides) and, where the
        District's record set its direction, that direction (OWNER-DECISIONS
        216, `routing_tags_by_way`), but for a two-way record over an OSM
        one-way on the no-trail graph, which stays one-way (item 246,
        `variants.routing_for`). An approved override that wrote one of
        the same keys is the reviewed value and stands; the no-trail graph's
        closure still runs after this (`variants.inject`, item 219)."""
        routed = context.routing_tags_by_way.get(way.osm_id)
        if routed:
            routed = variants.routing_for(variant, way.tags, routed)
        if not routed:
            return way.tags
        overridden = sorted(key for key in routed if way.tags.get(key) != way.source_tags.get(key))
        if overridden:
            # The reviewed row speaks for the reverse direction, so only the
            # direction itself is taken from the record: the closure's
            # `oneway:bicycle=yes` beside an approved `bicycle:backward=yes`
            # makes upstream close the with-flow direction instead.
            logger.info(
                "way %s: an approved override set %s, so the District's direction record "
                "sets only the way's one-way",
                way.osm_id,
                ", ".join(overridden),
            )
            routed = {
                key: routed[key] for key in ("oneway",) if key in routed and key not in overridden
            }
        return {**way.tags, **routed}

    def inject_tags() -> None:
        reference = context.require_reference()
        context.work_dir.mkdir(parents=True, exist_ok=True)
        classify_facilities()

        for variant in variants.Variant:
            per_way_tags: dict[int, dict[str, str]] = {}
            node_lists: dict[int, list[int]] = {}
            dropped: set[int] = set()

            for way in context.ways:
                injected = variants.inject(
                    variant,
                    routing_tags(way, variant),
                    way.osm_id,
                    reference.sidepath_bridge_ids,
                    reference.mass_ride_only_bridge_ids,
                )
                if injected is None:
                    dropped.add(way.osm_id)
                    continue

                # Everything this rebuild has to say about the way's own OSM
                # tags, which the first version computed and then threw away -
                # so the e-bike extract was identical to the standard one and
                # an e-bike route could run where e-bikes are barred.
                #
                # Diffed against the tags the *source* carried, not against
                # `way.tags`. `write_extract` rebuilds every way's tags from
                # the source PBF and applies this mapping over them, so a key
                # that is not in here is the source's value whatever
                # `way.tags` says - and `way.tags` is the working copy the
                # override stage has already corrected. Against it an approved
                # `access` override diffed away against itself on every
                # variant: `apply_access` wrote `bicycle=yes`, `variants.inject`
                # handed back those same tags for STANDARD and NO_TRAIL, the
                # comparison found no change, and the graph was built exactly
                # as if the row had never been approved.
                #
                # Internal keys are dropped here rather than at the writer,
                # because this diff is the only thing that puts a key the
                # source did not carry into a variant extract. `_jurisdictions`
                # is an annotation for this process, not a tag for a PBF.
                changes = {
                    key: value
                    for key, value in injected.items()
                    if way.source_tags.get(key) != value
                    and not key.startswith(extract.INTERNAL_PREFIX)
                }

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
                #
                # Withheld in two cases, because this tag is not just another
                # derived value: the transform writes the `bicycle` key from
                # it, so wherever it is emitted it is the last word on that
                # key, and something else has already had the first.
                legal = reference.bridge_bicycle_legal.get(way.osm_id)
                overruled = context.bicycle_override_directions.get(way.osm_id, frozenset())
                if overruled == overrides.BOTH_DIRECTIONS:
                    # An approved access override wrote a bicycle key onto this
                    # way for both directions. `bridge_may_be_granted` reads
                    # `access` and `vehicle` and never the bicycle keys -
                    # correctly, since a legality row is itself a correction to
                    # OSM's `bicycle` tagging - so with the tag emitted the
                    # checked-in fixture overwrote the reviewed row in whichever
                    # direction it ran:
                    # `bicycle=no` over a legality of true came back as
                    # `bicycle=yes`, and `bicycle=yes` over a legality of false
                    # was flattened to `no`. The override table is the plan's
                    # sole audited path for an access correction (PLAN:18, :28)
                    # and the fixture is a checked-in file, so the fixture is
                    # what gives way - on every variant, since the row is a
                    # legal fact and not a variant's opinion.
                    #
                    # Only where the row overruled it both ways. The fixture
                    # writes the plain `bicycle` key, and Valhalla's transform
                    # lets `bicycle:forward`/`bicycle:backward` override that
                    # one direction at a time, so a row writing one of them
                    # already wins its own direction with the tag emitted.
                    # Withheld there too, the fixture's grant was lost in the
                    # direction the row never mentioned: `bicycle:forward=no`
                    # on a bridge the fixture opens over OSM's `bicycle=no`
                    # served it barred both ways.
                    legal = None
                elif variant is variants.Variant.EBIKE and variants.bars_electric_bicycle(way.tags):
                    # The e-bike variant bars this way by writing `bicycle=no`
                    # (`variants.inject`), and a legality of true would be
                    # granted straight back over it by the transform. Declined
                    # here rather than in the Lua because this loop knows which
                    # variant it is building and the transform does not: one
                    # script serves all three extracts, so the guard it can
                    # write reads the `electric_bicycle` tag and therefore
                    # declines the grant on the standard and no-trail variants
                    # too, where no e-bike rule applies and the fixture's row
                    # should stand.
                    legal = None
                elif (
                    variant is not variants.Variant.NO_TRAIL
                    and way.osm_id in reference.mass_ride_only_bridge_ids
                ):
                    # The same reason, for the owner's mass-ride-only roadways
                    # (2026-09-26): `variants.inject` bars them on this variant,
                    # and the row's legality of true would be granted straight
                    # back over the bar by the transform. The no-trail variant
                    # keeps the roadway and keeps the legality with it.
                    legal = None
                if legal is not None:
                    derived["bridge_bicycle"] = legal
                if stress is not None:
                    derived["stress_tier"] = int(stress.tier)
                derived.update(
                    facility_derived(
                        variant, way.osm_id, context.facility_by_way, context.car_free_by_way
                    )
                )
                if way.osm_id in context.cemetery_ways:
                    # No cut-through: reached only from or to a point inside.
                    derived["cemetery"] = True
                lit = lit_value(way.tags)
                if lit is not None:
                    derived["lit"] = lit
                reason = context.no_bicycle.get(way.osm_id)
                if reason is not None and not (
                    variant is variants.Variant.OFFROAD and reason in trail_closures.OFFROAD_KEEPS
                ):
                    derived["no_bicycle"] = reason
                if way.osm_id in context.destination_only:
                    derived["destination_only"] = zoo.DESTINATION_ONLY

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

    def graph_outputs(build_dir: Path, config: dict) -> dict[str, Path]:
        """What a finished graph is made of, by name relative to its directory: the
        tile archive and the two databases (named by the build config), the build
        log and the build config itself."""
        mjolnir = config["mjolnir"]
        named = {
            str(Path(mjolnir[key]).relative_to(build_dir)): Path(mjolnir[key])
            for key in ("tile_extract", "admin", "timezone")
        }
        named[checkpoint.BUILD_LOG] = build_dir / checkpoint.BUILD_LOG
        named[checkpoint.BUILD_CONFIG] = build_dir / checkpoint.BUILD_CONFIG
        return named

    def graph_lua_dirs(config: dict) -> list[Path]:
        """The Lua the build reads: the image's copy and, where this container has
        it, the directory the build config names (compose bind-mounts the working
        tree at /conf/lua)."""
        found = [Path(_setting("BASE_DIR")) / "lua"]
        named = Path(config["mjolnir"].get("graph_lua_name", "")).parent
        if named.is_dir() and named not in found:
            found.append(named)
        return found

    def build_tiles() -> None:
        # Each variant builds into its own dated directory through a config
        # derived from its serving config: valhalla_build_tiles has no
        # tile-directory option, so the directory has to come from the file,
        # and the serving config names the graph being served.
        #
        # The admin and timezone databases are built here too, into the same
        # dated directory, because the retargeted config is what names them and
        # nothing else ever writes there. Neither is a function of the variant:
        # the timezone database is a function of the world, and the admin
        # database is a function of the merged extract, which is one file every
        # variant's admin build was handed. So the first variant builds each of
        # them and the rest copy the file - one ~100 MB download and one parse
        # of the 1-2 GB merged PBF per rebuild, rather than one and three.
        #
        # A resumed attempt finds the graphs an earlier attempt of this job
        # finished: each has a manifest (written last) naming what it was built
        # from and what it produced. A graph whose manifest is valid and whose
        # inputs and outputs all still match is kept - including as the source
        # of the admin and timezone copies - and any other directory of this
        # build is partial or stale and is deleted and built again.
        if context.merged_pbf is None:
            raise ReferenceDataMissing(
                "no merged extract to build admin data from; FETCH_EXTRACT produces it"
            )
        admin_source: Path | None = None
        timezone_source: Path | None = None
        concurrency = _setting("REBUILD_TILE_CONCURRENCY")
        for variant in variants.Variant:
            build_dir = tiles.build_dir(context.tiles_dir, variant, context.build_id)
            fingerprint: dict | None = None
            outputs: dict[str, Path] = {}
            fingerprint_hashing = 0.0
            if context.checkpoints:
                hashing_from = context.hasher.seconds
                try:
                    config_path, serving = tiles.build_config(
                        context.config_dir, context.tiles_dir, variant, context.build_id
                    )
                    outputs = graph_outputs(build_dir, serving)
                    fingerprint = checkpoint.graph_fingerprint(
                        variant_pbf=context.variant_pbf(variant),
                        merged_pbf=context.merged_pbf,
                        config=serving,
                        build_dir=build_dir,
                        lua_dirs=graph_lua_dirs(serving),
                        elevation_tiles=context.elevation_tiles,
                        hasher=context.hasher,
                    )
                except Exception:  # noqa: BLE001 - checkpoints are best effort
                    bookkeeping_failed(f"fingerprinting the {variant.value} graph")
                    fingerprint, outputs = None, {}
                fingerprint_hashing = context.hasher.seconds - hashing_from
            if context.resumed and build_dir.exists():
                problem = "there is no fingerprint to check it against"
                if fingerprint is not None:
                    try:
                        problem = checkpoint.graph_problem(
                            build_dir,
                            variant=variant,
                            build_id=context.build_id,
                            job_id=context.job_id,
                            fingerprint=fingerprint,
                            outputs=outputs,
                            hasher=context.hasher,
                        )
                    except Exception as error:  # noqa: BLE001 - not usable means rebuild it
                        logger.exception("could not check the %s graph", variant.value)
                        problem = f"it could not be checked ({type(error).__name__}: {error})"
                if problem is None:
                    context.build_configs[variant] = config_path
                    context.build_logs[variant] = (build_dir / checkpoint.BUILD_LOG).read_text(
                        encoding="utf-8"
                    )
                    mjolnir = serving["mjolnir"]
                    admin_source = admin_source or Path(mjolnir["admin"])
                    timezone_source = timezone_source or Path(mjolnir["timezone"])
                    context.graphs_reused.append(variant.value)
                    logger.info("reusing the %s graph from build %s", variant.value, build_dir)
                    continue
                logger.warning(
                    "rebuilding the %s graph in %s: %s", variant.value, build_dir, problem
                )
                # `this_build` is the adopted manifest's build id, not the context's:
                # two sources that must agree before anything is deleted.
                checkpoint.remove_partial_graph(
                    context.tiles_dir,
                    variant,
                    context.build_id,
                    this_build=context.resumed_build_id,
                )
            started = time.monotonic()
            config_path = tiles.write_build_config(
                context.config_dir,
                context.tiles_dir,
                variant,
                context.build_id,
                concurrency=concurrency,
            )
            context.build_configs[variant] = config_path
            mjolnir = json.loads(config_path.read_text())["mjolnir"]
            admin_db = Path(mjolnir["admin"])
            timezone_db = Path(mjolnir["timezone"])
            commands = tiles.tile_build_commands(
                config_path,
                context.variant_pbf(variant),
                admin_pbf=context.merged_pbf,
                admin_db=admin_db,
                timezone_db=timezone_db,
                admin_source=admin_source,
                timezone_source=timezone_source,
            )
            # Kept per variant: the Lua-fallback and violation checks are asked
            # of each variant's own log, and one joined string would let the
            # first match answer for all three.
            context.build_logs[variant] = "\n".join(
                _run_tile_command(run, command).log for command in commands
            )
            admin_source = admin_source or admin_db
            timezone_source = timezone_source or timezone_db
            context.graphs_built.append(variant.value)
            # The log is kept beside the graph whatever the checkpoint setting says:
            # a resumed attempt's VALIDATE_TILES reads a reused graph's log from it.
            # It is written once all of the graph's commands have succeeded, so a
            # graph whose build failed has none; that failure's output is in the
            # exception (the run row) and the rebuild's own log.
            log_path = build_dir / checkpoint.BUILD_LOG
            try:
                log_path.write_text(context.build_logs[variant], encoding="utf-8")
            except OSError:
                bookkeeping_failed(f"writing the {variant.value} graph's build log")
            if context.checkpoints and fingerprint is not None:
                # And the manifest is the last thing written: a graph without one
                # is, by definition, not finished.
                try:
                    if checkpoint.write_graph_manifest(
                        build_dir,
                        variant=variant,
                        build_id=context.build_id,
                        job_id=context.job_id,
                        fingerprint=fingerprint,
                        outputs=outputs,
                        concurrency_used=concurrency,
                        seconds=time.monotonic() - started,
                        hasher=context.hasher,
                        hash_seconds=fingerprint_hashing,
                    ):
                        context.checkpoints_written += 1
                except Exception:  # noqa: BLE001 - checkpoints are best effort
                    bookkeeping_failed(f"writing the {variant.value} graph's manifest")

    def map_class_of(osm_id: int, tags: dict[str, str]) -> facility.MapClass:
        """The map's class for a way, agreeing with what routing does with it.

        A sidewalk the CBD rule bars to bicycles (OWNER-DECISIONS 104) is a way
        a bicycle may not use, left to the base map like any other (89); a
        singletrack every ride type avoids (90, 91, 111) is not drawn as a
        trail the router will never send anyone down. The paved trails the
        singletrack rule exempts stay trails on both.
        """
        if osm_id in context.cbd_sidewalks:
            return facility.MapClass.BARRED
        if osm_id in context.short_paths_hidden or osm_id in context.singletracks:
            return facility.MapClass.HIDDEN
        base = facility.map_class(tags)
        reason = context.no_bicycle.get(osm_id)
        if reason is not None and reason != trailaccess.MTB and base is facility.MapClass.ROAD:
            # A trail the NO-BIKE-PATHS rules close (the Zoo's, a hiking path, a
            # private golf-cart path) is not drawn as a bike facility; the base
            # map shows it as it is (OWNER-DECISIONS 278, 290(b)). The
            # mountain-bike class stays, with the tile's `mtb` property, which
            # the map reads to draw it as not for routes (452a, superseding
            # 452's hiding and 290(b)'s faint drawing); a future MTB mode would
            # draw it as routable.
            return facility.MapClass.BARRED
        return base

    def dc_blocks_of(osm_id: int) -> tuple:
        """The District Roadway Block records a way lies along, for its Mass Ride
        width (OWNER-DECISIONS 404); none outside DC or where no block reached it."""
        facts = context.road_facts_by_way.get(osm_id)
        if facts is None or facts.agency != agency_roads.DC_AGENCY:
            return ()
        return facts.block_facts

    def write_segments() -> None:
        from .schema import schema_exists

        if not schema_exists(context.staging_schema):
            raise RuntimeError(
                f"{context.staging_schema} does not exist; FETCH_EXTRACT resets it and "
                "must have run first"
            )

        reference = context.require_reference()
        classify_facilities()
        dc_rules = massflow.DcRules(
            wide_lane_ft=_setting("MASS_RIDE_DC_WIDE_LANE_FT"),
            wide_lane_cap_ft=_setting("MASS_RIDE_DC_WIDE_LANE_CAP_FT"),
            verified_reversible_blocks=frozenset(
                _setting("MASS_RIDE_DC_VERIFIED_REVERSIBLE_BLOCKS")
            ),
            ended_reversible_streets=frozenset(_setting("MASS_RIDE_DC_ENDED_REVERSIBLE_STREETS")),
        )
        rows: list[dict] = []
        for way in context.ways:
            stress = context.stress_by_way[way.osm_id]
            trail = variants.is_trail_class(way.tags, way.osm_id, reference.sidepath_bridge_ids)
            # A mountain-bike trail never qualifies as a long trail (OWNER-DECISIONS
            # 378): it has no route level and no name to chain a run by.
            mountain_bike = (
                way.osm_id in context.mountain_bike_ways
                or trail_routes.is_mountain_bike_way(way.tags)
            )
            way_facility = context.facility_by_way.get(way.osm_id, "none")
            car_free_when = sorted(context.car_free_by_way.get(way.osm_id, ()))
            # Only a way the zoomed-out map draws is named for a run or judged as
            # a bridge (operations review N-2: a street's name is never read).
            zoomed_out_trail = trail_routes.is_zoomed_out_trail(way_facility, trail, car_free_when)
            long_trail = not mountain_bike and zoomed_out_trail
            way_map_class = map_class_of(way.osm_id, way.tags).value
            # The z12-13 ride layer (OWNER-DECISIONS 391): a path or an LTS 1 street
            # that can be in a long enough run; its length is derived after the rows
            # are written (`trail_routes.derive_calm_runs`), from 0 here.
            calm_candidate = trail_routes.is_calm_candidate(
                zoomed_out_trail=zoomed_out_trail,
                mountain_bike=mountain_bike,
                mtb_only=way.osm_id in context.mtb_only,
                is_trail_class=trail,
                stress_tier=int(stress.tier),
                map_class=way_map_class,
            )
            # Why a bicycle may not use it, or why an override reopened it, for the map's
            # road panel (OWNER-DECISIONS 441a); the router says whether it may.
            access_reason = facility.bike_access_reason(
                way.tags,
                no_bicycle=context.no_bicycle.get(way.osm_id),
                overridden=way.osm_id in context.bicycle_override_ways,
            )
            for ordinal, piece in extract.iter_segments(way):
                rows.append(
                    writers.segment_row(
                        way.osm_id,
                        ordinal,
                        piece,
                        stress,
                        sinuosity=sinuosity([Point(lon, lat) for lon, lat in piece]),
                        is_trail_class=trail,
                        is_unpaved=inferred_unpaved(way.tags),
                        is_rough=is_rough(way.tags),
                        lit=lit_value(way.tags),
                        facility=way_facility,
                        car_free_when=car_free_when,
                        map_class=way_map_class,
                        separate_bikeway=facility.has_separate_bikeway(way.tags),
                        mtb_only=way.osm_id in context.mtb_only,
                        walk_bike=way.osm_id in context.walk_bike,
                        road_speed_mph=_smallint(getattr(stress, "speed_mph", None)),
                        road_lanes=_smallint(getattr(stress, "lanes", None)),
                        mass_usable_width_m=massflow.usable_width_rounded(
                            way.tags,
                            getattr(stress, "lanes", None),
                            dc_blocks_of(way.osm_id),
                            dc_rules,
                        ),
                        # The graph's direction, not item 109's relief reading: a
                        # divided road's carriageway is one-way here.
                        road_oneway=getattr(stress, "graph_oneway", None),
                        trail_name=trail_routes.way_name(
                            way.tags, context.route_names.get(way.osm_id)
                        )
                        if long_trail or calm_candidate
                        else None,
                        calm_run_m=0 if calm_candidate else None,
                        roadside=facility.roadside_start(
                            way.tags, way_facility, drawn_trail=trail and way_map_class == "road"
                        ),
                        trail_route=0 if mountain_bike else context.trail_routes.get(way.osm_id, 0),
                        trail_bridge=3
                        if long_trail and trail_routes.is_bridge_way(way.tags)
                        else 0,
                        bike_access_reason=access_reason,
                    )
                )
        writers.write_segments(context.staging_schema, rows)
        # Not kept on the context any more: this stage runs before the tile build
        # now, and millions of row dicts held through it are memory the host does
        # not have. Nothing read them.
        del rows
        trail_routes.derive_trail_runs(context.staging_schema)
        trail_routes.derive_calm_runs(context.staging_schema)
        trail_routes.derive_roadside(context.staging_schema)

    def staging_checks() -> None:
        """The VALIDATE_SEGMENTS checks that read the staging schema alone, which is
        why a resumed attempt can run them again."""
        assert_mass_capacity(
            mass_capacity.capacity_summary(context.staging_schema),
            median_range=_setting("REBUILD_MASS_CAPACITY_MEDIAN_RANGE"),
        )
        sentinel_ways = tuple(_setting("REBUILD_SENTINEL_LONG_TRAIL_WAYS"))
        assert_long_trails(
            trail_routes.long_trail_summary(
                context.staging_schema, sentinel_ways, LONG_TRAIL_FLOOR_RUN_M
            ),
            sentinel_ways,
            _setting("REBUILD_LONG_TRAIL_FLOORS"),
        )

        calm_path_sentinels = tuple(_setting("REBUILD_SENTINEL_CALM_PATH_WAYS"))
        calm_street_sentinels = tuple(_setting("REBUILD_SENTINEL_CALM_STREET_WAYS"))
        assert_calm_runs(
            trail_routes.calm_run_summary(
                context.staging_schema,
                (*calm_path_sentinels, *calm_street_sentinels),
                CALM_PATH_RUN_M,
                CALM_ROAD_RUN_M,
            ),
            calm_path_sentinels,
            calm_street_sentinels,
            _setting("REBUILD_CALM_RUN_FLOORS"),
        )

    def validate_segments() -> None:
        """Everything that needs no graph: the segment rows and the in-memory
        classification, checked before the hours of tile building rather than after.

        When it passes, the classification checkpoint is written (last, and only
        if the inputs are still what they were at the start).
        """
        if context.resumed:
            # The context was never loaded, so only the checks that read the
            # staging schema can run, and only when their numbers have changed.
            if context.revalidate_staging:
                staging_checks()
                try:
                    refresh_validation_fingerprint()
                except Exception:  # noqa: BLE001 - checkpoints are best effort
                    bookkeeping_failed("recording the new validation numbers")
            return
        assert_reference_lts4_street(
            context,
            _setting("REBUILD_SENTINEL_LTS4_STREET"),
            _setting("REBUILD_SENTINEL_LTS4_MIN_SHARE"),
            _setting("REBUILD_SENTINEL_LTS4_NORTH_OF_LAT"),
            _setting("REBUILD_SENTINEL_LTS4_NORTH_MIN_SHARE"),
        )
        assert_owner_stretches(context, _setting("REBUILD_SENTINEL_STRETCHES"))
        assert_military_closures(
            context,
            _setting("REBUILD_SENTINEL_MILITARY_CLOSED_WAYS"),
            _setting("REBUILD_SENTINEL_MILITARY_MIN_CLOSED"),
        )
        assert_secured_closures(
            context,
            _setting("REBUILD_SENTINEL_SECURED_CLOSED_WAYS"),
            _setting("REBUILD_SENTINEL_SECURED_MIN_CLOSED"),
        )
        staging_checks()
        # Computed here, where the ways are, and held (and checkpointed) for
        # VALIDATE_TILES, which reads the graphs and needs no ways.
        context.closure_probes = closure_probes(context)
        if context.checkpoints:
            try:
                write_classification_checkpoint()
            except Exception:  # noqa: BLE001 - checkpoints are best effort
                bookkeeping_failed("writing the classification checkpoint")
        if context.release_after_classification:
            context.release_classification()

    def write_classification_checkpoint() -> None:
        """Write the classification manifest: last, atomically, and only when what it
        would say is still true."""
        if context.start_fingerprint is None or context.merged_pbf is None:
            return
        measured = measure_fingerprint(context.merged_pbf)
        moved = checkpoint.changed_inputs(context.start_fingerprint["inputs"], measured["inputs"])
        if moved:
            logger.warning(
                "no classification checkpoint: these inputs changed while the rebuild ran: %s",
                ", ".join(moved),
            )
            return
        pbfs = {variant: context.variant_pbf(variant) for variant in variants.Variant}
        absent = [str(path) for path in pbfs.values() if not path.is_file()]
        if absent:
            logger.warning("no classification checkpoint: %s not written", ", ".join(absent))
            return
        state = checkpoint.staging_state(context.staging_schema)
        if state is None or state["segment_rows"] is None:
            logger.warning("no classification checkpoint: no staging schema to describe")
            return
        token = checkpoint.new_token()
        variant_facts = checkpoint.variant_pbf_facts(pbfs, context.hasher)
        # The token goes onto the schema first and the manifest second: the manifest
        # is the commit, and a token with no manifest beside it is inert.
        checkpoint.stamp_staging(context.staging_schema, token)
        summary = context.override_report.summary() if context.override_report else None
        checkpoint.atomic_write_json(
            checkpoint.classification_path(context.work_dir),
            {
                "format": checkpoint.FORMAT,
                "job_id": context.job_id,
                "build_id": context.build_id,
                "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "fingerprint": measured,
                "variant_pbfs": variant_facts,
                "staging": {
                    "schema": context.staging_schema,
                    "segment_rows": state["segment_rows"],
                    "border_crossing_rows": state["border_crossing_rows"],
                    "token": token,
                },
                "closure_probes": [
                    {"way_id": p.way_id, "lon": p.lon, "lat": p.lat, "reason": p.reason}
                    for p in context.closure_probes or []
                ],
                "singletracks": sorted(context.singletracks),
                "override_summary": summary,
                # Every hash this attempt has read so far (both extracts, the code,
                # the reference data, the variant extracts), out of its budget.
                "hash_seconds": round(context.hasher.seconds, 1),
            },
        )
        context.checkpoints_written += 1
        logger.info(
            "classification checkpoint written for job %s build %s",
            context.job_id,
            context.build_id,
        )

    def refresh_validation_fingerprint() -> None:
        """After the staging checks have passed against new numbers, record them, so
        the next attempt does not run them again."""
        manifest = checkpoint.read_classification(context.work_dir)
        if manifest is None or manifest.get("build_id") != context.build_id:
            return
        manifest["fingerprint"]["validation"] = measure_fingerprint(context.merged_pbf)[
            "validation"
        ]
        checkpoint.atomic_write_json(checkpoint.classification_path(context.work_dir), manifest)

    def validate_tiles() -> None:
        if set(context.build_logs) != set(variants.Variant):
            raise ValidationFailed(
                "not every variant produced a build log, so there is nothing to check the "
                f"missing ones against: have {sorted(v.value for v in context.build_logs)}"
            )
        for variant, build_log in context.build_logs.items():
            build_config = context.build_configs.get(variant)
            if build_config is None:
                raise ValidationFailed(
                    f"the {variant.value} variant produced a build log and no build config, "
                    "so there is nothing to say which transform its build was told to load"
                )
            assert_lua_script_was_loaded(build_log, build_config, variant.value)
            assert_no_rule_violations(build_log, variant.value)
        assert_admin_and_timezone_databases_were_built(context.build_configs)
        assert_elevation_reached_the_tiles(sample_grade())
        assert_derived_tags_reached_the_tiles(sample_derived_tag(), DERIVED_SENTINEL_EXPECTED)
        weekend = sample_weekend_tag()
        if weekend != WEEKEND_SENTINEL_EXPECTED:
            raise ValidationFailed(
                f"the weekend graph reports {weekend!r} on Sligo Creek Parkway (way "
                f"{WEEKEND_SENTINEL_WAY_ID}), not {WEEKEND_SENTINEL_EXPECTED!r}: it was not "
                "derived as the weekend twin, so a weekend ride on it would not prefer the "
                "roads closed to cars"
            )
        assert_bicycle_closures_reached_the_tiles(sample_closures())

    def swap() -> None:
        # The classification checkpoint is deleted before the swap, never after: from
        # the first rename on, staging is the live schema and a resume into it would
        # be a resume into a promoted build. If the swap fails and undoes itself
        # completely - the one case where the staging schema is again exactly what
        # the manifest describes - the same manifest is put back, so the job's retry
        # re-runs VALIDATE_TILES and SWAP instead of the whole rebuild. It is
        # verified like any other on the way in. An undo that did not finish
        # (`SwapUndoIncomplete`), or a process that died, leaves it deleted.
        saved = checkpoint.read_classification(context.work_dir)
        checkpoint.discard_classification(context.work_dir)
        try:
            context.swap_outcome = promotion.perform_swap(
                context.tiles_dir, context.build_id, context.upstreams
            )
        except promotion.SwapUndoIncomplete:
            raise
        except Exception:
            if saved is not None and saved.get("build_id") == context.build_id:
                checkpoint.atomic_write_json(
                    checkpoint.classification_path(context.work_dir), saved
                )
            raise

    def reconcile_after_swap() -> None:
        context.drift_report = reconcile.drift_report(
            context.build_id,
            _setting("SEGMENT_SCHEMA_LIVE"),
            _setting("SEGMENT_SCHEMA_RETIRED"),
        )

    def unless_resumed(handler: Callable[[], None]) -> Callable[[], None]:
        """A stage the classification checkpoint stands in for. Whether this attempt
        resumes is decided when FETCH_EXTRACT runs, after the stage list is fixed,
        so the stages are skipped here rather than named in `run_rebuild`'s `skip`."""

        @functools.wraps(handler)
        def maybe() -> None:
            if context.resumed:
                logger.info("%s: kept from the classification checkpoint", handler.__name__)
                return
            handler()

        return maybe

    handlers = {
        Stage.FETCH_EXTRACT: fetch_extract,
        Stage.LOAD_REFERENCE_DATA: unless_resumed(load_reference_data),
        Stage.ELEVATION: ensure_elevation,
        Stage.CONFLATE_VOLUME: unless_resumed(conflate_volume),
        Stage.CLASSIFY_STRESS: unless_resumed(classify_stress),
        Stage.TAG_JURISDICTIONS: unless_resumed(tag_jurisdictions),
        Stage.APPLY_OVERRIDES: unless_resumed(apply_overrides),
        Stage.INSERT_BORDER_NODES: unless_resumed(insert_border_nodes),
        Stage.INJECT_TAGS: unless_resumed(inject_tags),
        Stage.WRITE_SEGMENTS: unless_resumed(write_segments),
        Stage.VALIDATE_SEGMENTS: validate_segments,
        Stage.BUILD_TILES: build_tiles,
        Stage.VALIDATE_TILES: validate_tiles,
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


def _read_back(sample: Callable[[], _Read]) -> _Read:
    """Run one of the validation reads, with a refusal by the service told from
    a failure of the command.

    `valhalla_service` in one-shot mode answers a request it cannot satisfy by
    writing a `valhalla_exception_t` body to stdout and exiting 1 - "No suitable
    edges near location" is the one this pipeline will meet, because both
    sentinels are coordinates nobody has confirmed against a real extract. The
    exit status is all `_run_command` sees, so that arrived as `CommandFailed`,
    which is deliberately retryable, and the weekly job answered a sentinel that
    had moved by rebuilding every tile five times over.

    A refusal carrying an error code is terminal: the next attempt sends the
    same shape to the same graph. Everything else keeps the class it had - a
    mirror that dropped, a binary killed - because that is the failure a retry
    does fix.
    """
    try:
        return sample()
    except CommandFailed as failure:
        refusal = tiles.valhalla_exception(failure.output.stdout)
        if refusal is None:
            raise
        raise ValidationFailed(
            "valhalla_service refused a validation read of the built tiles: "
            f"error_code {refusal['error_code']}: {refusal.get('error', '(no message)')}. "
            "A refused request is answered no differently by a rebuilt graph, so this "
            "is not retried; the sentinel edges in settings are what to check first."
        ) from failure


def _least_grade_across_variants(context: RebuildContext, run) -> float:
    """Every variant's build must have baked elevation, so the check is the
    smallest grade any of them reports on the known steep edge."""
    steep = _setting("REBUILD_SENTINEL_STEEP_EDGE")
    grades = [
        _read_back(
            functools.partial(tiles.sample_grade, run, context.build_configs[variant], steep)
        )
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
    return _read_back(
        functools.partial(
            tiles.sample_cycle_lane,
            run,
            config_path,
            _setting("REBUILD_SENTINEL_DERIVED_EDGE"),
            DERIVED_SENTINEL_WAY_ID,
        )
    )


def _weekend_cycle_lane(context: RebuildContext, run) -> str | None:
    config_path = context.build_configs.get(variants.Variant.WEEKEND)
    if config_path is None:
        raise ValidationFailed("the weekend variant has no build config to read back")
    return _read_back(
        functools.partial(
            tiles.sample_cycle_lane,
            run,
            config_path,
            _setting("REBUILD_SENTINEL_WEEKEND_EDGE"),
            WEEKEND_SENTINEL_WAY_ID,
        )
    )


def _closures_across_variants(context: RebuildContext, run) -> dict:
    """Read the gate's probes back from every variant's staged graph, after
    writing them where the post-swap probe will look for them."""
    held = getattr(context, "closure_probes", None)
    probes = held if held is not None else closure_probes(context)
    try:
        write_closure_reports(
            context.work_dir / DISCREPANCY_REPORT_DIR, probes, context.singletracks
        )
    except OSError:
        logger.warning("bicycle-closure probe list not written", exc_info=True)
    readbacks = {}
    for variant in variants.Variant:
        config_path = context.build_configs.get(variant)
        if config_path is None:
            continue
        held = [
            probe
            for probe in probes
            if not (
                variant is variants.Variant.OFFROAD and probe.reason in trail_closures.OFFROAD_KEEPS
            )
        ]
        readbacks[variant] = _read_back(
            functools.partial(tiles.read_closures, run, config_path, held)
        )
    return readbacks


# How many times a valhalla_build_tiles that aborted is run again. Valhalla
# 3.5.1 builds tiles on `mjolnir.concurrency` threads, and each thread frees its
# own spatialite connections to the admin and timezone databases when it
# finishes (src/mjolnir/graphbuilder.cc:436,446; src/mjolnir/util.cc:211-219).
# `spatialite_cleanup_ex()` calls libxml2's non-thread-safe `xmlCleanupParser()`,
# so two threads finishing together can free the same memory, and glibc aborts
# the process with "double free or corruption". Upstream serialised the cleanup
# in valhalla/valhalla#5005, first released in 3.6.0. The race is timing, not
# data: one rebuild lost its weekend graph on one attempt and its offroad graph
# on the next, from the same inputs, after the other graphs had built.
#
# So one abort of that one command is run again, from the start (a build from
# the initialize stage purges the tile level directories it is writing into,
# src/mjolnir/util.cc:252-271), inside whatever remains of the deadline. Any
# other failure, and a second abort, fails the stage as before.
TILE_BUILD_ABORT_RETRIES = 1

# The signals a valhalla_build_tiles can die of that a second run has cleared.
# SIGABRT is the double free above. SIGSEGV (-11) is the same race seen as a
# crash instead of an abort: the freed memory is touched before glibc notices
# (job 8408, 2026-10-09; OWNER-DECISIONS 459). The retry is the same one - once,
# from the start, in whatever is left of the deadline.
RETRYABLE_TILE_SIGNALS = (-signal.SIGABRT, -signal.SIGSEGV)


def _run_tile_command(
    run: Callable[[Sequence[str]], tiles.CommandOutput],
    command: Sequence[str],
    retries: int = TILE_BUILD_ABORT_RETRIES,
) -> tiles.CommandOutput:
    """Run one tile-build command, running an aborted valhalla_build_tiles again.

    Only `valhalla_build_tiles`, and only SIGABRT or SIGSEGV: a crash in the admin
    build or the extract is not the race above, and an ordinary non-zero exit is a
    refusal that will say the same thing twice. The deadline is the runner's:
    `_run_command` raises `RebuildTimedOut` when nothing is left for the retry.
    """
    retryable = Path(command[0]).name == "valhalla_build_tiles"
    attempt = 0
    while True:
        try:
            return run(command)
        except CommandFailed as failure:
            if not retryable or failure.returncode not in RETRYABLE_TILE_SIGNALS:
                raise
            if attempt >= retries:
                if not attempt:
                    raise
                raise CommandFailed(
                    failure.command, failure.returncode, failure.output, retries=attempt
                ) from failure
            attempt += 1
            logger.warning(
                "valhalla_build_tiles %s (%s); running it again, retry %d of %d: %s",
                "aborted" if failure.returncode == -signal.SIGABRT else "crashed",
                signal.Signals(-failure.returncode).name,
                attempt,
                retries,
                shlex.join(command),
            )


def _run_command(
    command: Sequence[str],
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    timeout: float | None = None,
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
    thing VALIDATE_TILES calls, so the rebuild died there every week and nothing could
    ever promote. See tiles.CommandOutput.

    A command that exits non-zero raises `CommandFailed` carrying the end of
    both streams, because `subprocess.run(check=True)` raises an error whose
    text is the argv and the exit status and whose captured output nothing was
    reading. See that class.
    """
    # Whether a timeout here would be the rebuild's budget running out, or only the
    # caller's own shorter limit on this one command (the closure gate's reads). The
    # worker retries the first kind when the attempt made progress (OWNER-DECISIONS
    # 459a) and never the second: a wedged read is not a slow rebuild.
    budget_bound = deadline is not None
    if deadline is not None:
        remaining = deadline - clock()
        if remaining <= 0:
            raise RebuildTimedOut(f"no time left to run {command[0]}")
        budget_bound = timeout is None or remaining <= timeout
        timeout = remaining if timeout is None else min(timeout, remaining)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as error:
        error.budget_exhausted = budget_bound
        raise
    except subprocess.CalledProcessError as error:
        output = tiles.CommandOutput(error.stdout or "", error.stderr or "")
        failure = CommandFailed(command, error.returncode, output)
        # Logged as well as raised. The exception reaches an operator through
        # the job row and the alert, which is the right place for it and is not
        # where somebody reading the rebuild's own log at the moment it failed
        # is looking; and a handler that catches this - none does today - would
        # otherwise take the only copy of the diagnosis with it.
        logger.warning("%s", failure)
        raise failure from error
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
