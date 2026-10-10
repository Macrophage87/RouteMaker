# Valhalla 3.5.1 to 3.6.3

The backlog item "Valhalla 3.6" (OWNER-DECISIONS 459a and 459b: the cloud rebuild
comes after checkpoints and Valhalla 3.6). Written 2026-10-10.

## What was chosen, and why

- **3.6.3**, the last 3.6 release (2026-02-19). The backlog names 3.6. Newer tags
  exist (3.7.0 to 3.9.1 on ghcr.io); this change does not take them. Each would
  be a separate upgrade with its own read of the release notes.
- **The plain image**, `ghcr.io/valhalla/valhalla:3.6.3`, built from upstream's
  `docker/Dockerfile` (it was the root `Dockerfile` at 3.5.1). Its runner is still
  `ubuntu:24.04` with no ENTRYPOINT, CMD or USER, so the compose commands are
  unchanged. Its sibling `valhalla-scripted` has an ENTRYPOINT and is not a
  drop-in.
- **All five serving routers and the pipeline image move together.**
  `tests/test_images.py` already holds them to one tag.

Sources:

- The release notes: CHANGELOG.md at tag 3.6.3,
  https://github.com/valhalla/valhalla/blob/3.6.3/CHANGELOG.md.
- The 3.5.1 and 3.6.3 source trees, compared file by file. The file:line citations
  below are into the 3.6.3 tree.

## What 3.6 changes for a bicycle, and what RouteMaker does about it

The project rule is that unclear bicycle access counts as closed. Three upstream
changes would have opened ways that rule keeps closed, so the transform now
narrows them first.

| Upstream change | Effect on its own | RouteMaker |
|---|---|---|
| Access lists read part by part, and any granting part wins (#5560, 3.6.1) | `bicycle=no;yes` and `access=private;no` become rideable | `narrow_access_lists` reduces a list to its most restrictive part before the remap or upstream reads it: `no` if any part is `no`, else the first part that is not a plain grant. The Python models read lists the same way (`routemaker.tags.most_restrictive`), and a test holds the two together. |
| `vehicle` now speaks for bicycles (#5802, 3.6.2) | `vehicle=agricultural` closes a way. `vehicle=yes` opens a footway, and also a motorway. | Footways with a `vehicle` grant are left open: a bicycle is a vehicle in OSM, so this tagging is not unclear. A motorway or ramp whose only grant is `vehicle` gets `bicycle=no`. A mapper's own `bicycle=yes` there still stands. |
| `smoothness=impassable` closes every vehicle mode (#5023) | Closed, but the remap's stress penalty, the closed-road `cycleway=track` and a bridge legality row could each have reopened it | `physically_closed` (`impassable=yes` or `smoothness=impassable`) blocks all three writes. The closed-road write had the same gap for `impassable=yes` before this change; that is fixed too. |

These upstream changes are taken as they come:

- **`access:conditional` is now a timed restriction for every mode** (#5048). A way
  closed "no @ (hours)" is closed to bicycles at those hours. The C++ parser has
  read `bicycle:conditional` this way since 3.5.1, which the remap's comments did
  not know. FOLLOWUP-CONDITIONAL-ACCESS below covers it.
- **Barrier nodes.** `fence`, `wall`, `jersey_barrier`, `barrier_board` and `debris`
  now close a node to every mode unless an access tag reopens it.
  `kissing_gate`, `motorcycle_barrier`, `chain` and `bar` are treated as bollards,
  which bicycles pass. `sliding_beam` is treated as a gate. This narrows where it
  bites, which the rule allows. On the Baltimore sample, 5 `fence` nodes close and
  1 `chain` node opens. The DC count is a host step below.
- **Smoothness now sets the surface where no `surface` or `tracktype` tag does**
  (#4949): bad becomes compacted, very_bad dirt, horrible gravel, and so on. Some
  untagged-surface ways are priced rougher. No preset uses `avoid_bad_surfaces = 1`,
  so nothing new is excluded.
- **Routers.**
  - The matrix's `check_reverse_connection` now defaults to true, so Best order
    times may move slightly.
  - New config keys arrive with upstream's defaults: hierarchy limits (bicycles
    ignore them), hard exclusions (off) and linear cost factors (unused).
  - `shutting_seconds` was renamed `shutdown_seconds`. The value is 1 either way.
- **Errors.** Valhalla's catch-all codes 199, 299 and 499 are now HTTP 500 instead
  of 400 (#5359). `core.routing` still reads them as one refused request, not a
  router outage. Otherwise one bad request would have marked the weekend or
  off-road router down for every rider.
- **Tile builds.**
  - The thread-exit double free behind `REBUILD_TILE_CONCURRENCY` and the SIGABRT
    retry is fixed (#5005, src/mjolnir/sqlite3.cc:78-91). The default stays 2 and
    the retry stays until host rebuilds show no abort. OPERATIONS.md, "Tile build
    threads", says when to try 4.
  - Tiles are now written to a temp file and then renamed (#5888). A crashed build
    can leave `*.gph_*.tmp` files behind; `initialize` purges them.
  - The timezone script now fetches the 2025b "-1970" dataset, so expect fewer
    `tz_world` rows than 3.5.1's 444. The check only needs more than 0.
- **Unchanged, re-checked:**
  - The bicycle edge cost formula. 3.6.3 multiplies by a linear-feature factor,
    which is 1 unless a request sends one.
  - Node transition pricing.
  - mtb:scale handling, and wood and boardwalk read as compacted.
  - The Lua entry-point contract.
  - `valhalla_service CONFIG [WORKERS]` and its one-shot form.
  - Every request key and response field `core.routing` and `core.junctions` use.
  - "Using LUA script:".

**Tiles: 3.6.3 reads 3.5.1 tiles.** The load check compares major versions only,
and only warns (src/baldr/graphtile.cc:320-323). Every struct change went into
spare bits, so the routers can move before the first 3.6.3 rebuild. This was
read from source, not run. The reverse direction, 3.5.1 serving 3.6.3 tiles, has
not been checked, so keep the last 3.5.1 build until a 3.6.3 rebuild validates.

## What was run, in the cloud

Docker cannot pull the ghcr.io image here (its blob host is blocked). The
`pyvalhalla` 3.6.3 wheel on PyPI carries the same release's `valhalla_build_tiles`,
`valhalla_build_admins` and `valhalla_service`, linked against LuaJIT, so these ran
for real:

- **A tile build of Valhalla's own `test/data/baltimore.osm.pbf`** (3,857 highway
  ways) with RouteMaker's generated standard config and `lua/graph.lua`. The log
  showed `Using LUA script: .../lua/graph.lua`.
- **Routing on that build.** A bicycle `/route` and `trace_attributes` for every
  preset's costing options, and `core.routing.pieces_of_trace` on the answers.
  All of them parsed. `trace_attributes` returns `node.traffic_signal` now.
- **`tests/test_tile_build_access.py`**, which builds a fixture with the real
  `valhalla_build_tiles` and checks that every bicycle closure reaches the tiles.
  It passed. It had never run in a cloud session before.
- **The real transform over all 3,857 Baltimore ways**, under 3.5.1's and 3.6.3's
  graph.lua with this remap. No way changed bicycle access. 5 of 95 tagged nodes
  changed: the barrier rows above.
- **The test suite** against a PostGIS container: see the PR for the before and
  after.

## Host steps (Stephen's WSL; not done from the cloud)

Rebuilds run 07:30-21:30 UTC, one at a time. Nothing here publishes anything.

1. **Bring in main and build the pipeline image.** Tag the old image first so
   there is a rollback point.
   ```sh
   docker tag ghcr.io/macrophage87/routemaker-pipeline:dev ghcr.io/macrophage87/routemaker-pipeline:pre-valhalla36 </dev/null
   docker compose pull valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend valhalla-offroad </dev/null
   docker compose build rebuild </dev/null
   ```
2. **The closure check, against the new image.** It takes about 2 s. Exit 0 means
   every closure held.
   ```sh
   scripts/check_tile_build_access.sh
   ```
3. **Count what 3.6 changes on the real extract**, before rebuilding. This is
   read-only and runs inside the rebuild container.
   ```sh
   docker compose exec -T rebuild sh -c 'f=/data/extracts/source.osm.pbf; for e in n/barrier=jersey_barrier,fence,wall,barrier_board,debris w/smoothness=impassable w/access:conditional w/vehicle; do printf "%s: " "$e"; osmium tags-filter -R -O -o /tmp/c.pbf "$f" "$e" >/dev/null && osmium fileinfo -e -g data.count.nodes /tmp/c.pbf | tr "\n" " " && osmium fileinfo -e -g data.count.ways /tmp/c.pbf; done; rm -f /tmp/c.pbf' </dev/null
   ```
   Each line prints a node count, then a way count. The barrier line is the one
   to read: those nodes close to bicycles under 3.6.3.
4. **Recreate the routers and the rebuild service**, with no rebuild job todo or
   doing. This is never a plain `up -d`.
   ```sh
   docker compose up -d --no-deps --no-build --force-recreate valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend valhalla-offroad rebuild </dev/null
   ```
   The routers now serve the existing 3.5.1 tiles. Run `~/rmdata/verify-pm.sh`.
5. **One rebuild by hand, in the window:**
   `docker compose exec -T rebuild ./manage.py run_rebuild_now`. Then:
   - check its VALIDATE result and the reference routes;
   - check whether `retry 1 of 1` appears in the log. Under 3.6.3 it should not.
6. **Rollback.** Pin the five routers back to 3.5.1, retag
   `pre-valhalla36` as `dev`, and recreate. If a 3.6.3 rebuild has already
   promoted, `rollback_rebuild` puts the 3.5.1 tiles back first.
7. **Beta** (`compose.beta.yaml`, off-road router) follows the same pin. It needs
   the owner's go, as every beta step does.

## Follow-ups left open

- **FOLLOWUP-CONDITIONAL-ACCESS.** The parkway-reversal remap
  (`remap_conditional_access`) was written believing Valhalla reads no conditional
  key. In fact the parser applies `bicycle:conditional` (and, from 3.6.0,
  `access:conditional`) as timed restrictions against the request's `date_time`.
  Whether the static resolution is still needed, or now conflicts, wants a look.
  This change leaves its behaviour alone.
- **`trailaccess.upstream_open` and `sac_scale=hiking` on a footway.** The model
  calls the footway open, but upstream keeps it closed, in 3.5.1 and 3.6.3 alike.
  This predates the upgrade, and only ever marks a way that is already closed.
- **The remap's `bounded_surface`.** It names `paved_rough`, `path` and
  `impassable`, which the parser reads by substring: `paved_rough` reads as
  paved_smooth, and `path` and `impassable` fall back to the class default. This
  predates the upgrade. Any reviewer surface penalty that lands on one of those
  names is weaker than intended.
- **`lua/graph.lua`'s load order.** If `require("routemaker_remap")` fails after
  upstream's globals are installed, the build runs the stock transform with only
  a log line. This also predates the upgrade.
- **Newer Valhalla** (3.7 to 3.9) when there is a reason to take it.
