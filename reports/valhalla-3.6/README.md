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
| `vehicle` now speaks for bicycles (#5802, 3.6.2) | `vehicle=agricultural` closes a way. Any `vehicle` grant opens a way the class or `access` kept closed, a motorway included, and so do restricted grants such as `vehicle=delivery`. | A public grant (every part `yes`, `designated`, `permissive` and the like) opens a footway or path: a bicycle is a vehicle in OSM, so that is not unclear. Any other `vehicle` grant gets `bicycle=no` where the class or `access` would have kept bicycles out, and on a motorway or ramp every `vehicle` grant does. A way with its own `bicycle`, `bicycle:forward`, `bicycle:backward`, `cycleway`, `bicycle_road` or `cyclestreet` tag is left to that tag (`vehicle_reopens_for_bicycle`). |
| `smoothness=impassable` closes every vehicle mode (#5023) | Closed, but the remap's stress penalty, the closed-road `cycleway=track` and a bridge legality row could each have reopened it | `physically_closed` (`impassable=yes` or `smoothness=impassable`) blocks all three writes. The closed-road write had the same gap for `impassable=yes` before this change; that is fixed too. |

These upstream changes are taken as they come:

- **`access:conditional` is now a timed restriction for every mode** (#5048). A way
  closed "no @ (hours)" is closed to bicycles at those hours. The C++ parser has
  read `bicycle:conditional` this way since 3.5.1, which the remap's comments did
  not know. FOLLOWUP-CONDITIONAL-ACCESS below covers it.
- **Barrier nodes** (#5217).
  - Newly closed to every mode unless an access tag reopens them: `fence`,
    `wall`, `jersey_barrier`, `barrier_board` and `debris`. A route that crossed
    one of these nodes no longer can.
  - Newly passable by bicycle, as bollards: `kissing_gate`, `motorcycle_barrier`,
    `chain` and `bar`. They now close to motor vehicles instead. `sliding_beam`
    is read as a gate.
  - On the Baltimore sample, 4 `fence` nodes close. One `chain` node changes, but
    only for motor vehicles, which it now closes; bicycles passed it before and
    still do. The DC count, an upper bound on what closes, is host step 3.
- **Smoothness as a surface (#4949): held back.** From 3.6.0 the parser prices
  `smoothness` as a surface where no `surface` or `tracktype` tag says:
  excellent and good as paved_smooth, intermediate as paved_rough (the
  cobblestone class), bad as compacted, very_bad as dirt, horrible as gravel,
  very_horrible as path. OWNER-DECISIONS 440 counts only cobblestone as paved but
  rough, so the remap strips `smoothness` from such ways for now and they are
  priced as under 3.5.1 (`M.SMOOTHNESS_SURFACE_IGNORED`). `smoothness=impassable`
  is kept, since it closes the way. Whether to take upstream's reading is
  FOLLOWUP-SMOOTHNESS-SURFACE in PLAN.md.
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
    can leave `*.tmp*` files in the tile directory; `initialize` purges them.
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
not been checked, so keep the last 3.5.1 build until a 3.6.3 rebuild validates,
and roll the tiles back before the routers (host step 6).

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
  changed: the 4 fences and the chain above.
- **The test suite** against a PostGIS container: see the PR for the before and
  after.

## Host steps (Stephen's WSL; not done from the cloud)

Rebuilds run 07:30-21:30 UTC, one at a time. Nothing here publishes anything.
Run these from the repository root.

1. **Note the rollback point, bring in main, build the images.** The api and
   worker images carry the new error handling, and the pipeline image carries
   the new Valhalla binaries.
   ```sh
   git rev-parse HEAD > ~/rmdata/pre-valhalla36.sha    # before the pull: the commit being replaced
   git pull --ff-only origin main
   docker tag ghcr.io/macrophage87/routemaker-api:dev ghcr.io/macrophage87/routemaker-api:pre-valhalla36 </dev/null
   docker tag ghcr.io/macrophage87/routemaker-pipeline:dev ghcr.io/macrophage87/routemaker-pipeline:pre-valhalla36 </dev/null
   docker compose pull valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend </dev/null
   docker compose build api rebuild </dev/null
   ```
   Where the off-road router runs, also
   `docker compose --profile offroad pull valhalla-offroad </dev/null`.
2. **The closure check, against the new pipeline image.** About 2 s. Exit 0 means
   every closure held.
   ```sh
   scripts/check_tile_build_access.sh
   ```
3. **Count what 3.6 changes on the real extract**, before rebuilding. Read-only,
   inside the rebuild container.
   ```sh
   docker compose exec -T rebuild sh -c 'f=/data/extracts/source.osm.pbf; for e in n/barrier=jersey_barrier,fence,wall,barrier_board,debris n/barrier=kissing_gate,motorcycle_barrier,chain,bar w/smoothness=impassable w/access:conditional w/vehicle; do printf "%s: " "$e"; osmium tags-filter -R -O -o /tmp/c.pbf "$f" "$e" >/dev/null && osmium fileinfo -e -g data.count.nodes /tmp/c.pbf | tr "\n" " " && osmium fileinfo -e -g data.count.ways /tmp/c.pbf; done; rm -f /tmp/c.pbf' </dev/null
   ```
   Each line prints a node count, then a way count. The first line is the most
   that can newly close to bicycles (an access tag on the node can still reopen
   it). The second is the barriers bicycles now pass and motor vehicles do not.
4. **Recreate the services**, with no job todo or doing and not during the 07:00
   backup. First check the queue; this must print no rows:
   ```sh
   docker compose exec -T postgis psql -U routemaker -d routemaker -c "SELECT id, task_name, status FROM procrastinate_jobs WHERE status IN ('todo','doing')" </dev/null
   ```
   Then, never as a plain `up -d`:
   ```sh
   docker compose up -d --no-deps --no-build --force-recreate valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend api worker rebuild </dev/null
   ```
   Where the off-road router runs, separately:
   `docker compose --profile offroad up -d --no-deps --no-build --force-recreate valhalla-offroad </dev/null`.
   Never name `valhalla-offroad` without `--profile offroad`. The routers now
   serve the existing 3.5.1 tiles. Run `~/rmdata/verify-pm.sh`.
5. **One rebuild by hand, in the window:**
   `docker compose exec -T rebuild ./manage.py run_rebuild_now`. Then:
   - check its VALIDATE result and the reference routes;
   - check whether `retry 1 of 1` appears in the log. Under 3.6.3 it should not.

   After it promotes, restart the routers onto the new tiles, then run the
   probes and the check:
   ```sh
   docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend </dev/null
   docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py locate </dev/null
   ~/rmdata/verify-pm.sh
   ```
   Where the off-road router runs, also
   `docker compose --profile offroad restart valhalla-offroad </dev/null`.
6. **Rollback.** If a 3.6.3 rebuild has promoted, run `rollback_rebuild` first,
   because 3.5.1 routers reading 3.6.3 tiles is unchecked. Then put back the
   code and the images, and recreate as in step 4:
   ```sh
   git checkout "$(cat ~/rmdata/pre-valhalla36.sha)" -- compose.yaml valhalla lua src docker
   docker tag ghcr.io/macrophage87/routemaker-api:pre-valhalla36 ghcr.io/macrophage87/routemaker-api:dev </dev/null
   docker tag ghcr.io/macrophage87/routemaker-pipeline:pre-valhalla36 ghcr.io/macrophage87/routemaker-pipeline:dev </dev/null
   ```
   This leaves the checkout modified; once the cause is understood,
   `git checkout main -- compose.yaml valhalla lua src docker` restores it.
7. **Beta, with the owner's go.** The beta's release agent stops on this change
   (an `image:` line and `lua/` both changed; BETA-RUNBOOK, the deploy table), so
   it is a hand release. The beta runs the four routers, not the off-road one.
   Following BETA-RUNBOOK: pull 3.6.3 there
   (`scripts/beta/beta-compose.sh pull valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend`),
   ship the tiles built at home under 3.6.3 (step 5) with
   `scripts/beta/ship-data.sh`, then release as the runbook's "A new release sha"
   section says: `beta-compose.sh up -d` the four routers, which recreates them
   on 3.6.3 (a `restart` alone keeps the old image), then restart them for the
   `lua/` change.

## Follow-ups left open

All are in PLAN.md's backlog.

- **FOLLOWUP-SMOOTHNESS-SURFACE.** Whether to price `smoothness` as a surface,
  as 3.6 does. Held back above.
- **FOLLOWUP-CONDITIONAL-ACCESS.** The parkway-reversal remap
  (`remap_conditional_access`) was written believing Valhalla reads no conditional
  key. In fact the parser applies `bicycle:conditional` (and, from 3.6.0,
  `access:conditional`) as timed restrictions against the request's `date_time`.
  Whether the static resolution is still needed, or now conflicts, wants a look.
  This change leaves its behaviour alone.
- **FOLLOWUP-VALHALLA-36-LEFTOVERS.** Five smaller items, all predating the
  upgrade but found in its review: the remap's `bounded_surface` names that the
  parser misreads; `lua/graph.lua` falling back to the stock transform if the
  remap fails to load; `upstream_open` and `sac_scale=hiking` on a footway;
  retiring the tile-build concurrency guard and retry after clean 3.6.3 rebuilds;
  and the unchecked 3.5.1-reads-3.6.3-tiles direction.
- **Newer Valhalla** (3.7 to 3.9) when there is a reason to take it.
