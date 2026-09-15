### Routing and tile pipeline — REVISE (4 blocking)

Reviewer verified the round-1/2 fixes in this area as real and correct (vendored files
confirmed byte-identical to upstream by md5; the wrapper, the positive node ids, the
generated configs and the conditional remap all check out against 3.5.1 source, cited by
file and line). The blockers below are ground earlier rounds did not reach.

**B1. The stress-tier remap grants bicycle access on `access=no` ways that Valhalla drops.**
CONFIRMED BY ME, end to end through the real transform:

    private farm track (track/access=no/gravel)   upstream filter=1 → with remap filter=0 bike_fwd=true bike_bwd=true
    closed service road (service/access=no)       upstream filter=1 → with remap filter=0 bike_fwd=true bike_bwd=true
    gated living street (living_street/access=no) upstream filter=1 → with remap filter=0 bike_fwd=true bike_bwd=true

`classify()` rates all three LTS1 (it is a stress classifier and does not read access), then
`remap_way` writes `cycleway=track`, from which upstream derives bicycle access. The graph
asserts a legal claim in the *widening* direction, with no override row and no review —
bypassing the override table PLAN makes the sole audited path for access corrections. This is
exactly the geometry the rural Group Ride references sit on: gated fire roads, closed NPS
service roads, private Loudoun farm tracks. `bicycle=no` is safe (upstream's table wins); the
hole is specifically `access=no`. Fix is one condition alongside the existing `tags.cycleway`
and `is_trail_class` guards. Neither Lua suite covers a restricted way at tier 1.

**B2. The three variant configs are byte-identical and share one tile directory.** CONFIRMED BY
ME — and this one is mine, introduced this session:

    all three md5 f37b638c07c22e243758b51764ecb699 ;  all three tile_dir=/data/valhalla
    scripts/build_valhalla_configs.py:139  def build(variant: str): return merge(load_upstream_defaults(), OVERRIDES)

`build()` ignores its argument. `test_the_configs_are_what_the_generator_produces` compares each
file against `build(variant)` — identical things — so it cannot fail. Textbook "asserts the
function rather than the pipeline", the exact pattern I spent the session fixing.

Consequence: `valhalla_build_tiles` has no tile-directory CLI option, so the three builds
overwrite each other in `/data/valhalla` and only the last variant's graph survives — destroying
the whole of layer 1 (no-trail for Mass Ride, `electric_bicycle=no → bicycle=no` for E-bike).
Worse, the reviewer checked every configured path against compose: the rebuild service mounts
only `/tiles` and `/extracts`, so `/data/valhalla`, `/data/elevation` and `/conf/lua/graph.lua`
are covered by NOTHING. Tiles land on ephemeral container storage and vanish. There is no dated
tile directory and no promotion step anywhere, despite `rebuild.py`'s docstring claiming one.

**B3. The scheduled weekly rebuild cannot complete.** CONFIRMED BY ME — also mine:

    build_handlers(ctx)   # exactly as config.procrastinate.weekly_rebuild calls it
    missing stages: ['swap', 'reconcile']
    VALIDATE raises: ValidationFailed

Two independent stoppers: `validate()` raises in production (no samplers injected), and
`run_rebuild(handlers)` is called with the default empty `skip`, so `Stage.SWAP` raises
`StageNotImplemented`. My test monkeypatched `run_rebuild` itself, so it never touched the
handlers. (Reviewer hit the sampler guard first, I hit the Lua-log guard first — empty
build_log — same conclusion.)

**B4. There is no elevation stage; nothing produces or installs HGT tiles.**
`src/pipeline/elevation.py` is imported only by its own test. `Stage` has no elevation member,
no task runs `gdalwarp_command`, nothing fetches 3DEP, and `/data/elevation` is unmounted (B2).
Valhalla warns and continues, so grade is never baked: `use_hills` inert, Mass Ride's grade cap
with no `max_grade` to read, Recovery and Mountain Goat gain invariants tying. The plan's guard
(`assert_elevation_reached_the_tiles`) exists but is unreachable because of B3. Phase 1 lists
"elevation tiles" as a deliverable.

**SHOULD-FIX:** S1 the elevation config test asserts `mjolnir.additional_data.elevation`, which
the reviewer found no read of in 3.5.1 — the key Skadi reads is top-level; my build script's
comment claiming both are needed is wrong. S2 every crossings row has `osm_names: null` and
matching is exact-equality, so on a real extract the sidepath set is near-empty — the round-2 bug
moved from stale ids to unmatchable names; the test synthesises the extract from the fixture's
own names, so it cannot fail. S3 `error()` inside `ways_proc`/`nodes_proc` does NOT halt a build —
`LuaTagTransform::Transform` catches it and returns an empty tag map, so the border guard
silently removes the border node instead of refusing the build, the opposite of its comment.
S4 `gate_cost` stays inert on cycle barriers tagged `motor_vehicle=no`. S5 nothing runs
`valhalla_build_admins`/`valhalla_build_timezones` and nothing installs the reference data.

**NIT:** N1 `ACCESS_RANK` emits `customers`, which upstream maps to nil (access dropped, not
granted). N2 `rm:access_conditional_*` is written then stripped before anything reads it — a dead
write. N3 nothing converts `oneway:conditional`, which is how the parkway reversal is actually
tagged. N4 `max_exclude_locations` raised under a comment about polygons. N5/N6 notes on PLAN
wording and a no-op override block.
