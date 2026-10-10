# Valhalla 3.6.3 to 3.9.1

Written 2026-10-10. This follows the 3.6.3 upgrade (reports/valhalla-3.6/README.md)
the same day. The owner asked for the newest release once 3.6.3 was up, with a
large review panel "to check for hidden issues".

## What was chosen, and why

- **3.9.1**, the newest release (2026-10-01). It is nine days old, so no point
  release has had time to follow it. The host steps below keep the previous
  version as the rollback. 3.6.3 and 3.9.1 read each other's tiles, but not each
  other's configs: a 3.6.3 router aborts at start on the 3.9.1 `valhalla/*.json`
  (checked: `service_limits.auto_pedestrian.max_locations` is missing). So the
  checkout and the images always move together; see the host steps.
- **The same plain image**, `ghcr.io/valhalla/valhalla:3.9.1`. Its
  `docker/Dockerfile` differs from 3.6.3's by one line: how the locale list is
  made. The base is still `ubuntu:24.04`, the runtime packages are the same,
  and there is still no ENTRYPOINT, CMD or USER. The pipeline image's packages
  and binary checks need no change.
- **All five routers and the pipeline image move together**, as before.

Sources:

- The release notes: CHANGELOG.md at tag 3.9.1,
  https://github.com/valhalla/valhalla/blob/3.9.1/CHANGELOG.md (3.7.0, 3.8.0 to
  3.8.3, 3.9.0, 3.9.1).
- The 3.6.3 and 3.9.1 source trees, compared directory by directory (mjolnir,
  baldr, sif, loki, thor, tyr, lua, scripts, docker). The file:line citations
  below are into the 3.9.1 tree.

## What changes for a bicycle

**Access: nothing.** How access, oneway, the bicycle tags, barriers, sidewalks,
cycleways, smoothness, `sac_scale` and `mtb:scale` are read is unchanged. The
3.6.3 guards (`narrow_access_lists`, `vehicle_reopens_for_bicycle`,
`physically_closed`, the smoothness strip) still sit in front of an unchanged
reading. The bicycle costing code is the same apart from destination-only
plumbing, but one input it reads from the tiles changed: see "Free turns where
no car road meets" below.

**Pricing: one change a rider can see.** From 3.7.0 the tile build gives a
junction no turn cost when no other edge there is open to cars (#5877;
src/mjolnir/util.cc:284-303). The bicycle turn cost and turn time apply only
where that cost is above 0 (src/sif/bicyclecost.cc:763-779), so turns between
trails, side paths and footways become free. Upstream's reason: such a node is
"not a real intersection", and the cost was phantom. On Baltimore trail trips
(249 trips of 0.6 to 3 mi (1 to 5 km) between bike-legal paths, three presets),
33 routes took a different line and ride times were 17 s (about 3%) shorter on
average, 52 s at most. Street trips were unchanged. There is no Lua hook for
this, so it is taken. (The 3.9.1 changelog files #5877 under 3.6.3, but the
3.6.3 source does not have it.)

Changes that do reach a bicycle, all taken as they come:

| Upstream change | What it does | RouteMaker |
|---|---|---|
| Time rules re-parsed without regex (#6230, 3.9.0; `src/mjolnir/timeparsing.cc`) | `access:conditional` and `bicycle:conditional` windows are read more faithfully: `Mo-Fr 07:00-19:00, Sa 08:00-12:00` is two windows (3.6.3 stretched the second to Mo-Sa); `08:00-20:00 Mo-Fr` is weekdays only (3.6.3: every day); `Su off` is no longer read as "closed all Sunday"; en-dash ranges and `07:00+` are read. | Taken. A `no @` window now covers what the tag says rather than more, so some ways are open at hours 3.6.3 closed them in error. That is a correct reading, not an unclear one. The common forms (`Sa,Su 07:00-19:00`, `Mo-Fr 06:45-09:30`, `Apr-Oct`, `;`-separated rules) parse the same in both. Checked by compiling both parsers on 76 strings. |
| `destination @ (...)` conditions (#6364, 3.9.1) | While the window applies, the way is marked destination-only. The first (bidirectional) search refuses it unless the route is already inside a destination-only stretch; the relaxed second pass opens it. At 3.6.3 the first pass refused it outright. (`valhalla/sif/dynamiccost.h:837-845`; `src/thor/route_action.cc:314-346`.) | Taken. The one new opening: a ride that has just used a destination-only way, such as a cemetery's or the Zoo spur (static `access=destination`, unchanged), may carry on into an adjacent way inside its window. |
| `surface=clay` and `laterite` read as dirt (#6171, 3.8.3) | Priced as dirt instead of the class default. | Taken. RouteMaker's own trail model already counts clay as a natural surface (`trailaccess.NATURAL_SURFACES`). |
| Bridge and tunnel grades clamped to ±3% (#5728, 3.7.0; `src/mjolnir/elevationbuilder.cc:200-207`) | The elevation model under a bridge is the valley floor, so a bridge read a false climb. | Taken. The router's hill pricing (`use_hills`) now sees at most ±3% on a bridge or tunnel. The elevation profile and climb list come from the route's own elevation, which this does not touch, so a bridge split into several edges can still show a dip there. The Mass Ride grade cap is not built yet; when it is, it will read the clamped grades. |
| `maxspeed=walk` read as 3 mph (5 km/h) (graph.lua, 3.7.0) | A walking-pace street is priced as a 3 mph (5 km/h) road. | Taken. Such a street is calmer, and now reads so. |
| Pedestrian areas (#6127, #6195) | `highway=pedestrian` + `area=yes` still makes no edge, as in 3.6.3. A new option (`mjolnir.pedestrian_areas`) would route pedestrians across a plaza, never bicycles. | Off, which is upstream's default; the configs say `false`. A plaza is no more rideable than before. |
| `amenity=parking` on a node (3.7.0; `src/mjolnir/pbfgraphparser.cc:2186`) | The node is typed as parking, in the same loop that types a gate or bollard, so on a gate also tagged `amenity=parking` whichever tag comes last wins. A gate typed as parking loses its gate cost and penalty and its private-access cost. | Guarded. `keep_barrier_type` (lua/routemaker_remap.lua) takes the parking tag off a gate or bollard after upstream's transform, so it stays a gate. Checked in a real 3.9.1 tile build: both tag orders came out as `parking` without the guard and as `gate` with it. Lua tests hold it. |
| `junction=intersection` (#5980) | Marks the edges inside a junction. For a bicycle the only effect is that the service-road penalty is skipped there. | Taken. |
| Access restrictions can be lifted per request (#5942, 3.8.0) | A request's `linear_cost_factors` with `ignore_access_restrictions` skips timed and mode restrictions on the edges it names. `bicycle=no` still holds. | RouteMaker builds every request itself and sends none. A test now holds that no source file sends either key. |

**The Baltimore census.** The real transform over all 3,857 highway ways of
Valhalla's Baltimore test extract, under 3.6.3's and 3.9.1's graph.lua with this
remap: one way differs, a pedestrian plaza, closed to bicycles under both. All
95 tagged nodes are the same.

## What changes for the code

- **Logging.** From 3.7.0 every program reads one top-level `logging` section
  and ignores the per-module ones (#5976; `src/midgard/logging.cc:371-381`).
  Upstream's default turns colour on, which would put escape codes into the
  build log the pipeline reads for "Using LUA script:". The configs now set the
  top-level section, colour off, and drop the dead per-module sections.
  Neither 3.6.3 nor 3.9.1 reads `long_request` anywhere in its source, so the
  setting that was meant to keep rider locations out of slow-request logs
  (OWNER-DECISIONS 395) guarded nothing. There is no such log to guard.
- **`/locate` lists `filtered_edges`** (#5987, 3.7.0): edges a heading, side or
  layer filter set aside. RouteMaker's locates send none of those, so the list
  is empty and nothing moves. The closure gate reads it anyway, so a filter
  added later cannot hide a probed way's edges and pass the gate on a probe it
  never read. Tests hold both.
- **Unchanged, re-checked:**
  - Error codes and their HTTP statuses: 199, 299 and 499 still return 500; 171,
    442 and 443 still return 400.
  - Every request key and response field `core.routing`, `core.junctions`,
    `core.segment_info` and `core.stoporder` use. The matrix adds a `cost` key.
  - `valhalla_service CONFIG [WORKERS]` and its one-shot form. The service
    listens on `tcp://` as before.
  - The log lines the pipeline reads ("Using LUA script:", the admin and time
    zone warnings, the extract-loaded line).
  - The `json` request parameter (#6099) is unused: every call is a POST.
- **New config keys** arrive with upstream's defaults: bounding circles for
  `/locate` (on), pedestrian areas (off), `dataset_id`, `mvt_max_age`, the
  `auto_pedestrian` limits, `max_exclude_polygons_vertices` (RouteMaker sends
  no polygons), and `thor.costmatrix.dijkstra_distance` (0, off).

## Tiles and the build

- **Configs do not go backwards.** A 3.6.3 or 3.5.1 router aborts at start on
  the regenerated `valhalla/*.json` (new `service_limits` sections it reads as
  modes). The routers bind-mount `./valhalla` and `./lua` from the checkout, so a
  `git pull` with no recreate, or an image rollback with no `git checkout` of
  those directories, takes routing down at the next restart.
- **3.9.1 reads 3.6.3 and 3.5.1 tiles, and 3.6.3 reads 3.9.1 tiles.** The tile
  header is still 272 bytes. Its one new field (`boundingcircles_offset_`) took a
  spare slot, and `date_created_` is still there despite the release note. The
  fixed-size records are unchanged. A 3.6.3 router never reads the new
  bounding-circle section, and a 3.9.1 router sees none on an older tile. The
  version check still only warns. So the routers can move before the first
  3.9.1 rebuild, and back after one. Read from source, not run.
- **The double-free fix** behind the tile-build retry is byte-identical
  (`src/mjolnir/sqlite3.cc`).
- **Memory.** The sort now runs chunks in parallel, capped at the build's
  concurrency (2 by default) and at 8. Each chunk is 512 MB of memory-mapped
  file, so at 2 up to two are touched at once. This is page cache, not heap.
- **Disk.** One new temporary file, `edge_shapes.bin` (8 bytes per way node),
  removed at the end of the build.
- **The time-zone script** fetches the 2026d data. On a host with `wslpath`, the
  new script turns its temp path into a Windows path, which would break it. Inside
  the pipeline container there is no `wslpath`, so never run the script on the WSL
  shell itself.
- **The build validate stage** now stamps every tile with a build id. That is
  extra I/O only.

## What was run, in the cloud

With the `pyvalhalla` 3.9.1 wheel's own `valhalla_build_tiles`,
`valhalla_build_admins` and `valhalla_service`:

- **`tests/test_tile_build_access.py`** with the real binaries: it passed.
- **A tile build of the Baltimore extract** with the generated standard config and
  `lua/graph.lua`. It logged "Using LUA script:", with no escape codes.
- **Routing on that build**, against a 3.6.3 build of the same extract.
  - Street trips: a bicycle `/route` and `trace_attributes` for each of the nine
    presets on three trips, and `core.routing.pieces_of_trace` on the answers.
    Every answer matched 3.6.3's: the same ways, lengths and times. One trip has
    no route on either version.
  - Trail trips: the free-turn change above, measured on 249 trips.
  - No elevation data in the cloud, so the bridge clamp was not exercised.
- **A verbose `/locate`**: `edges` carries every field the code reads.
- **The test suite** against a PostGIS container: see the PR.

## Host steps (Stephen's WSL; not done from the cloud)

If the 3.6.3 host steps (reports/valhalla-3.6/README.md) have not been run yet,
run these instead; they cover both upgrades. Rebuilds run 07:30-21:30 UTC, one
at a time. Nothing here publishes anything.

**Do steps 1 to 4 in one sitting**, inside the window and well before the weekly
rebuild (Tuesday 08:00 UTC). From the `git pull` in step 1 until step 4
recreates the services, the running routers and rebuild container are the old
version reading the new `lua/` and `valhalla/` from the checkout: a router
restart then crash-loops, and a rebuild would build with the new Lua on the old
binaries. If anything in step 1 fails, put the old files back before stopping:
`git checkout "$(cat ~/rmdata/pre-valhalla39.sha)" -- lua valhalla`. The
checkout's HEAD has already moved, so a retry's `git pull` changes nothing:
before retrying, bring the new files back with `git checkout HEAD -- lua valhalla`.

1. **Check the queue, note the rollback point, bring in main, build the
   images.** The queue check must print no rows; not during the 07:00 backup.
   The three guarded lines keep the first rollback point if the block is re-run.
   ```sh
   docker compose exec -T postgis psql -U routemaker -d routemaker -c "SELECT id, task_name, status FROM procrastinate_jobs WHERE status IN ('todo','doing')" </dev/null
   [ -s ~/rmdata/pre-valhalla39.sha ] || git rev-parse HEAD > ~/rmdata/pre-valhalla39.sha    # the commit being replaced
   docker image inspect ghcr.io/macrophage87/routemaker-api:pre-valhalla39 >/dev/null 2>&1 || docker tag ghcr.io/macrophage87/routemaker-api:dev ghcr.io/macrophage87/routemaker-api:pre-valhalla39 </dev/null
   docker image inspect ghcr.io/macrophage87/routemaker-pipeline:pre-valhalla39 >/dev/null 2>&1 || docker tag ghcr.io/macrophage87/routemaker-pipeline:dev ghcr.io/macrophage87/routemaker-pipeline:pre-valhalla39 </dev/null
   git pull --ff-only origin main
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
3. **Count what 3.9 changes on the real extract.** Read-only, inside the rebuild
   container (whose image is still the old one; osmium is the same).
   ```sh
   docker compose exec -T rebuild sh -c 'f=/data/extracts/source.osm.pbf; for e in w/access:conditional,bicycle:conditional n/amenity=parking w/surface=clay,laterite w/maxspeed=walk w/junction=intersection w/highway=pedestrian; do printf "%s: " "$e"; osmium tags-filter -R -O -o /tmp/c.pbf "$f" "$e" >/dev/null && osmium fileinfo -e -g data.count.nodes /tmp/c.pbf | tr "\n" " " && osmium fileinfo -e -g data.count.ways /tmp/c.pbf; done; rm -f /tmp/c.pbf' </dev/null
   ```
   Each line prints a node count, then a way count. The first is the ways whose
   time windows the new parser reads; the second the parking nodes (the guard
   keeps any that are gates or bollards); the rest are the pricing changes above.
   If the 3.6.3 steps were skipped, run that report's step 3 as well.
4. **Recreate the services.** Never as a plain `up -d`:
   ```sh
   docker compose up -d --no-deps --no-build --force-recreate valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend api worker rebuild </dev/null
   ```
   Where the off-road router runs, separately:
   `docker compose --profile offroad up -d --no-deps --no-build --force-recreate valhalla-offroad </dev/null`.
   Never name `valhalla-offroad` without `--profile offroad`. The routers now
   serve the existing tiles. Run `~/rmdata/verify-pm.sh`.
5. **One rebuild by hand, in the window:**
   `docker compose exec -T rebuild ./manage.py run_rebuild_now`. Then:
   - check its VALIDATE result and the reference routes. Trail routes may
     differ slightly: the free turns above;
   - check whether `retry 1 of 1` appears in the log. With the fix it should not.

   After it promotes, restart the routers onto the new tiles, then run the
   probes and the check:
   ```sh
   docker compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend </dev/null
   docker compose exec -T rebuild python3 scripts/probe_bicycle_closures.py locate </dev/null
   ~/rmdata/verify-pm.sh
   ```
   Where the off-road router runs, also
   `docker compose --profile offroad restart valhalla-offroad </dev/null`.
6. **Rollback.** Code and images go back together, and the services are
   recreated as in step 4:
   ```sh
   git checkout "$(cat ~/rmdata/pre-valhalla39.sha)" -- compose.yaml valhalla lua src docker scripts
   docker tag ghcr.io/macrophage87/routemaker-api:pre-valhalla39 ghcr.io/macrophage87/routemaker-api:dev </dev/null
   docker tag ghcr.io/macrophage87/routemaker-pipeline:pre-valhalla39 ghcr.io/macrophage87/routemaker-pipeline:dev </dev/null
   ```
   This leaves the checkout modified; once the cause is understood,
   `git checkout main -- compose.yaml valhalla lua src docker scripts` restores it.

   The tiles:
   - **Back to 3.6.3:** keep them. A 3.6.3 router reads 3.9.1 tiles.
   - **Back to 3.5.1** (the 3.6.3 steps were never run): 3.5.1 reading newer tiles
     is unchecked, so the tiles go back too, before the recreate.
     `rollback_rebuild` undoes only the latest promotion, once. Run it first
     without `--confirm` and read its plan. If only step 5's build has promoted
     under 3.9.1, run
     `docker compose exec -T rebuild ./manage.py rollback_rebuild --confirm </dev/null`.
     If the weekly rebuild has also promoted under 3.9.1, do not roll the tiles
     back: put back the code and images, recreate, then
     `docker compose exec -T rebuild ./manage.py run_rebuild_now </dev/null` to
     rebuild under 3.5.1. Until that rebuild promotes, the 3.5.1 routers serve
     3.9.1 tiles, the unchecked case above, so check routing with
     `~/rmdata/verify-pm.sh` straight after the recreate. After it promotes,
     restart the routers and check as in step 5.
7. **Beta, with the owner's go.** The beta's release agent stops on this change
   (an `image:` line and `lua/` both changed; BETA-RUNBOOK, the deploy table), so
   it is a hand release, as for 3.6.3. The beta runs the four routers, not the
   off-road one. Follow BETA-RUNBOOK, "Shipping an update later", from its start:
   - pause the agent first
     (`"$RM_STATE/cd/bin/auto-release.sh" pause --wait "valhalla 3.9.1 by hand"`,
     then `... status`), and follow `pause`'s verdict;
   - pre-pull the router image by name, since `beta-compose.sh` reads the
     checkout's `compose.yaml`, which still names the old version until the
     release checks out the new sha:
     `docker pull ghcr.io/valhalla/valhalla:3.9.1 </dev/null`;
   - ship the tiles built at home under 3.9.1 (step 5) with
     `scripts/beta/ship-data.sh`;
   - release the merged commit's `vX.Y.Z` tag as "A new release sha" says:
     `beta-compose.sh up -d` the four routers, which recreates them on 3.9.1 (a
     `restart` alone keeps the old image), then restart them for the `lua/`
     change;
   - then `... mark-deployed vX.Y.Z` and `... resume`.

## Follow-ups

Nothing new for the backlog. The 3.6.3 follow-ups (FOLLOWUP-SMOOTHNESS-SURFACE,
FOLLOWUP-CONDITIONAL-ACCESS, FOLLOWUP-VALHALLA-36-LEFTOVERS) still stand. The
time-rule parser change bears on FOLLOWUP-CONDITIONAL-ACCESS: Valhalla now reads
the parkway windows more faithfully, which is the reading that follow-up should
start from.
