# Deploy history

The per-release deploy notes from v0.8.1 to v0.31.0, moved out of docs/OPERATIONS.md on
2026-11-28 (the owner, "Streamline the release procedure"). They are a record of what each
release needed on the beta at the time; none is a step to repeat. How a release ships now is
docs/RELEASING.md, and anything a future release needs on the beta goes in its release pull
request.

## Deploying v0.31.0

Everything merged into `release/v0.31.0` since v0.30.4 (#1437 to #1469). Ships at once:
survey spots (#1449, #1450, #1457: a Layers switch, a sky-blue "?" on each low-confidence road,
a card of questions, the ride summary's list of spots passed, connector `survey_spots_near`);
via points ride the exact way they sit on (#1459, #1460), count as reached within a quarter
mile in Ride (#1461), and stay on an automatic re-route (#1463); saved routes take today's
directions for their own line (#1446); a route stretch says how much is on bridges (#1458);
the ride chart's close turns as one arrow and route junction markers that show the route's own
movement (#1439 to #1441); Plan's chart shows stop icons (#1437); beta builds print the GPS
position in small print in Ride (#1462); the agent park closures through the connector (#1466),
and the same agent on beta's worker (#1467, "The closure agent on the worker (v0.31.0)"): an
hourly `run_closure_agent` task (23 past each hour) that reads the park and county agencies'
pages with Claude and marks, extends and ends the closures it can place.

Takes effect only with a map rebuilt from v0.31.0 or later: Southwest Florida as a second area
(#1442, #1444; off until `RM_COVERAGE_AREAS` names it, "Map areas: turning on Southwest
Florida"), its beach path and low tides (#1445), restrooms beside paths and fountains (#1465),
school, hospital and similar service roads destination-only (#1454), gated communities and their
paths closed (#1453), Florida trail uses (#1456), sidewalks priced as side paths where the law
lets bikes ride them and as connectors where no road runs beside them (#1447, #1455), a sidewalk
beside a level 4 road with a read speed of 45 mph or more priced as a link, in DC-Baltimore too
(#1451, the owner's "merge that", 2026-11-26), footways joining two streets drawn (#1448) and a
trail's short join to a corner crosswalk ridden (#1464).

What changes for a deploy:

- migrations `0069_survey_spots` (survey answer and done tables), `0070_agent_closures`
  (`reviewed_closure.agent_key` and `extended_at`) and `0071_agent_key_db_default` (a database
  default for `agent_key`); the release agent snapshots the database before it migrates;
- `docker/api.Dockerfile` copies `fixtures/survey` into the image; `compose.yaml` adds
  `RM_COVERAGE_AREAS` (default `dc-baltimore`) to the Django services: leave it unset on beta
  and at home until the Florida map is swapped in, or the api takes Florida points with no roads;
- `lua/graph.lua` and `lua/routemaker_remap.lua` changed, so the release agent holds the tag as
  one that needs a map; the code ships alone with `ship-held --no-map`, and the Lua rules do
  nothing on today's map (no way carries `rm:campus_grounds` or `rm:sidewalk=sidepath` until the
  pipeline writes them);
- `docker/requirements-api.txt` adds `anthropic==2.10.0`, so the api image is rebuilt (the
  Release workflow's image); the worker is recreated and picks up `run_closure_agent`;
- the closure agent stays off ("off" on its run row) until the worker has
  `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID` and `ANTHROPIC_WORKSPACE_ID`
  (env.beta.template lists them; beta's `.env` holds them since 2026-11-28) and the token file
  (`ANTHROPIC_IDENTITY_TOKEN_FILE`, compose.beta.yaml's default `/run/anthropic-wif/token`) is
  mounted; when on, the worker
  also reaches api.anthropic.com, Nominatim, the OSM API and the agencies' pages;
- `compose.beta.yaml`'s worker binds the host's `/run/anthropic-wif` read-only (the identity
  token, `ANTHROPIC_IDENTITY_TOKEN_FILE` defaults to `/run/anthropic-wif/token`) with
  `group_add ${ANTHROPIC_WIF_GID:-986}` (#1469). The bind does not make its folder, so the
  beta host needs `/etc/tmpfiles.d/anthropic-wif.conf` before its next reboot (the closures
  thread gave the owner the line; the folder is there today, so this deploy starts);
- no `valhalla/` or nginx change.

- [ ] **The token folder** **(owner)**. `/etc/tmpfiles.d/anthropic-wif.conf` on the beta host,
  so `/run/anthropic-wif` comes back after a reboot.
- [ ] **The tag**. Once `test` and `a11y` are green on `main`: the Release workflow (Actions,
  "Release", Run workflow on main, version `v0.31.0`), started by the release thread after the
  owner's go to merge; it needs no approval, as the `release` environment has no reviewer.
- [ ] **Beta** **(owner)**. By hand, not `ship-held --no-map`: the env template's new
  `ANTHROPIC_*` lines are a stop that ship-held does not take (it answers map stops only), so
  v0.31.0 went out by docs/BETA-RUNBOOK.md, "Shipping an update later" (`pause --wait` first,
  then `mark-deployed v0.31.0` and `resume`). The ship shows the snapshot, migrations 0069 to
  0071, api and worker recreated, and `migrate --check` OK. From v0.32.0 an env template change
  is a note, not a stop.
- [ ] **Beta check.** The app says 0.31.0; `/api/coverage` is still one Polygon; Layers, Survey
  spots draws blue "?" marks in DC; answering one hides it and the count goes to 1; Mark closed
  and End still work on a closure; the `closure_agent` run row says "off" (or, with the
  federation settings in, a run at 23 past the hour).
- [ ] **Later, the closure agent** **(owner)**. Set the three federation settings and mount the
  token file, recreate the worker, watch one hourly run; then the session agent's hourly
  scheduled task is retired.
- [ ] **Rollback.** `auto-release.sh rollback --restore-db` (it loses survey answers and
  closures made since) with the v0.30.4 front end. `--keep-db` works for closures (0071 gives
  `agent_key` a database default), but deleting an account that answered a survey spot then
  fails on `survey_done`'s key, so delete that account's `survey_done` rows by hand first.
- [ ] **Later, the map** **(owner)**. The map rebuilt from v0.31.0 (or its release head),
  installed with `scripts/cloud/import-result.sh --beta`. Its log names the campus service
  roads made destination-only and the sidewalks priced as side paths; after the swap,
  `refresh_places.py`, the barrier snapshot and `build_intervals`. Florida only by turning on
  `RM_COVERAGE_AREAS` everywhere, as "Map areas: turning on Southwest Florida" says.

## Deploying v0.30.4

A patch on v0.30.3, on the owner's ask (2026-11-22, "release as a patch", "the other ones in flight
too"): everything merged into `release/v0.31.0` since v0.30.3. Each stress-tile request now has its
own time limit (20 s), so one request that never answers can no longer hold a queue slot, or the
load-time availability check, for the whole visit and leave the map with only the widest tiles'
few streets (#1433). Share route and Share ride copy the link where the browser has no share sheet,
or show it in a box to copy, and Save on Plan's map bar and Go's Save chip offers Share route
(#1431, docs #1432).

What changes for a deploy:

- front end only: no migration; no `lua/`, `valhalla/`, compose, nginx, Dockerfile or requirements
  change, so the beta's release agent deploys the tag by itself;
- no router restart and no map step.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.30.4`, then approve).
- [ ] **Beta check.** The app says 0.30.4; the stress colours show at every zoom after a long
  visit; Share route in Save & load copies the link in Firefox on a computer (no share sheet there).
- [ ] **Rollback.** The v0.30.3 front end.

## Deploying v0.30.3

A patch on v0.30.2, on the owner's ask (2026-11-22, "Submit everything in flight as a patch"):
everything merged into `release/v0.31.0` since v0.30.2. Go's tapped-spot card leads with the route
at that spot when a route is on the map (#1420); a planned route's own junctions keep their map
dots at the close zooms (#1423); connector drafts keep stop icons and names by number, so
`save_route` works on them (#1426); `osm_edit.py` may set `cycleway:<side>:separation` (#1421).
Two map changes take effect only with a map rebuilt from v0.30.3 or later: bike-open sidewalks
beside streets closed to public driving priced as paths (#1422, the Capitol grounds) and webs of
short walks drawn as the path network they are (#1427: anywhere a web of them runs 150 m or more
and meets the map at two or more places; the Washington Monument and Capitol grounds among them).

What changes for a deploy:

- no migration; no `valhalla/`, compose, nginx, Dockerfile or requirements change;
- `lua/graph.lua` and `lua/routemaker_remap.lua` changed (#1422), so the beta's release agent holds
  the tag as one that needs a map; the code ships alone with `auto-release.sh ship-held v0.30.3
  --no-map`, and the `lua/` change does nothing on today's map (no way carries
  `rm:no_public_traffic_sidewalk` until the pipeline sets it at the next rebuild);
- no router restart and no map step today; the rebuild these two changes need is listed below, as
  nothing on beta records it once v0.30.3 is marked deployed.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.30.3`, then approve).
- [ ] **Beta** **(owner)**. `~/routemaker-beta-state/cd/bin/auto-release.sh ship-held v0.30.3
  --no-map --dry-run`, then the same without `--dry-run`.
- [ ] **Beta check.** The app says 0.30.3; in Go, with a saved route loaded, a tap on the route
  opens a card that leads with the distance from the start; a planned route zoomed all the way in
  shows the dots of the rated junctions it rides through.
- [ ] **Rollback.** The `pre-rel` api image and the v0.30.2 front end, together.
- [ ] **Later, the map** **(owner)**. The next map rebuilt from v0.30.3 or later, installed with
  `scripts/cloud/import-result.sh --beta`. Its log says "sidewalks of streets closed to public
  driving priced as paths: N ways" and "short paths hidden from the map: N ways" (fewer than the
  last rebuild's); the walks round the Washington Monument are drawn.

## Deploying v0.30.1

A patch on v0.30.0, on the owner's ask (2026-11-21, "Let's send the Junction markers and other fixes
as a patch"): the raters' junction ratings shown as small dots in the stress colour, level 3 and up,
on a planned route (map, list, stress chart, Ride ribbon) and on the plain map from zoom 17 (every
rated junction at the closest zoom), with a card of each movement's level and wait, and Ride's turn
card bordered in a hard move's colour (#1291, with the new `GET /api/junctions/rated`); the Go
location dot refreshed every 15 s before a destination (#1406); accessibility fixes and the bottom
bar's "Plan" renamed "Planner" (#1401); the beta map swap holds the deploy lock against the router
timer and stops (exit 3) when a trail router did not start (#1409). #1291 also adds two rater briefs
and a pipeline change (short sidewalk links walked on the e-bike and Road Bike graphs) that takes
effect only at the next map rebuild.

What changes for a deploy:

- no migration; no `lua/`, `valhalla/`, compose, nginx, Dockerfile or requirements change, so the
  beta's release agent takes a tag made by the Release workflow by itself; no router restart, no map
  step;
- `scripts/beta/auto-release.sh` changed (#1409), so after the deploy the agent puts its own new
  files in `$RM_STATE/cd/bin` (the run log says "step: the release changed the agent"); only if the
  log says "WARNING: the agent's files could not all be reinstalled", run
  `scripts/beta/auto-release.sh install` from the v0.30.1 checkout;
- the segment panel names a sidewalk ridden as a last resort ("Last resort", a new `last_resort`
  field in the segment answer), on today's map;
- the pipeline change takes effect only with a map rebuilt from v0.30.1 or later: the e-bike and
  both Road Bike graphs then ride no sidewalk at all (the owner, 2026-11-14) and walk only the short
  links where a bike way meets a footway, so their routes beside Avoid roads may get longer;
- the dots read the `JunctionRater` table already loaded on beta; with no rows, the API answers
  `{"junctions": []}` and nothing is drawn.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.30.1`, then approve).
- [ ] **Beta.** The release agent deploys it; `auto-release.sh status` shows it.
- [ ] **Beta check.** The app says 0.30.1; a planned route through a busy junction shows a coloured
  dot there, and tapping it lists each movement's level and wait; the plain map at zoom 17 or closer
  shows dots; the bottom bar says "Planner".
- [ ] **Rollback.** The `pre-rel` api image and the v0.30.0 front end, together (the old front end
  never asks the new path; the new front end draws no map dots on the old api).

## Deploying v0.30.0

The release train's v0.30.0, on the owner's ask (2026-11-21, "Get ready to ship 0.30 when the map is
rebuilt"): Ride settings, the same in Plan and Go and now a screen of their own (a full screen on a phone, a
side panel on a computer), with "Waiting at lights and stops", "Sharp turns" (both in half steps) and "Fewer
turns" (#1367, #1374, #1376, #1384, #1391); a Surface picker from Paved only and Paved and gravel to Easy MTB trails and MTB
trails up to level 4, kept in links as `paved=1` (#1386, #1388); the rider's own named ride types, kept on the
account in `settings.own` and `goOwn` (no migration: the settings JSON; no points, vias, lines or notes accepted)
with what Go starts on and settings shared as JSON (#1385, #1391); waits weigh 2x on
pleasure and training rides, Group Ride and Cargo (Tandem's was already 2x), and the connector can raise them
(#1364, #1377, #1378); sharp turns, U-turns and jogs rank as more than one turn and turns are priced
by the speed they cost (#1363, #1366); Fast is as direct as possible at real time (#1378, #1381); Go
locks the route on the map until Edit route is opened (#1360), drops drawn icons on ride type chips
(#1361) and its route sheet never scrolls sideways (#1383); short bike-open links inside closed
campuses (#1359) and footways that close a gap between bike ways (#1362) are priced as links, which
takes effect with the map rebuilt from this branch (cloud-20261120b, commit e6c6f6a7; the commits
after it change no pipeline code); Geofabrik's per-state download folders (#1380). Junction dots, method C
trail levels and Virginia stay out.

What changes for a deploy:

- no migration; no `lua/`, `valhalla/`, compose, nginx, Dockerfile or requirements change, so the
  beta's release agent takes a tag made by the Release workflow by itself; no router restart;
- the api code runs on the old map too (#1359 and #1362 only change what the rebuild writes), so the
  tag and the map swap are separate steps, in either order;
- new link and API parameters (`waits=`, `sharpturns=`, `fewerturns=`; `wait_weight`,
  `sharp_turn_weight`) are optional; old links plan as before.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.30.0`, then approve).
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point, fast-forward the
  checkout, `docker compose build api`, recreate api and worker with no job todo or doing, then the
  front end.
- [ ] **Beta.** The release agent deploys it; `auto-release.sh status` shows it.
- [ ] **Beta check.** The app says 0.30.0; Ride settings (Plan and Go) opens its screen with both
  sliders, Fewer turns and Surface, and a link made there carries `waits=` and `sharpturns=`; a ride type
  saved under My ride types is there after a reload, signed in; Go keeps the route fixed on the
  map until Edit route; Fast's card reads "As direct as possible."
- [ ] **The map swap (owner's go)**, as "Rebuilding on the cloud box", once cloud-20261120b's bundle
  is checked. Then: the Rockville Pike side path at Medical Center (NIH) is routed through; the
  JunctionRater table still holds its rows; `scripts/refresh_places.py`, the barrier snapshot and
  `build_intervals` (commit `intervals.json`).
- [ ] **Rollback.** The `pre-rel` api image and the v0.29.0 front end, together: the old api refuses
  (422) the new `wait_weight` and `sharp_turn_weight` that a v0.30.0 page sends once a slider is moved.
  The map has its own rollback (the previous graph), and either runs with the other.

## Deploying v0.29.0

The release train's v0.29.0, on the owner's ask (2026-11-20, "Make 0.29 live"): Ride shows stops in
the ahead graph's turns row and names them on the cue card (#1352), the Interval stretches layer in
Go too (#1351), a crosswalk that carries a trail across a road priced as a link (#1353; takes effect
at the next map rebuild, since the price is written into the graph), the planner side of the
raters' junction ratings (#1354) and a test fix (#1350). Virginia stays out.

What changes for a deploy:

- one migration, `0068_junction_rater`: a new, empty table. The old code runs on it;
- no `lua/`, `valhalla/`, compose, nginx, Dockerfile or requirements change, so the beta's release
  agent takes a tag made by the Release workflow by itself, migration included; no map rebuild, no
  router restart;
- routing is unchanged until the table is loaded: with no rows, every junction keeps the model's
  price and wait.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.29.0`, then approve).
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point, fast-forward the
  checkout, `docker compose build api`, recreate api and worker with no job todo or doing
  (the migration runs), then the front end.
- [ ] **Beta.** The release agent deploys it; `auto-release.sh status` shows it.
- [ ] **Beta check.** The app says 0.29.0; Go, Map layers, Trails and terrain has "Interval
  stretches"; a ride with a stop shows it in the graph's turns row and the cue card names it.
- [ ] **Junction ratings (separate step, owner's go).** Not part of the deploy. Copy
  `junctions-stress-delay.csv.gz` and `junction-nodes.tsv` from the PC's
  `~/routemaker-exports/junctions-run` to the beta, then `manage.py load_junction_raters <csv.gz>
  <junction-nodes.tsv>` (dry: read the counts), then the same with `--confirm`. Takes effect from
  the next plan; undo is `JunctionRater.objects.all().delete()` in `manage.py shell`.
- [ ] **The open data download** gains a `junctions` layer (#1354's ratings, one point per node)
  once the ratings are loaded where the export runs; nothing to do at deploy.
- [ ] **Rollback.** The `pre-rel` api image and the v0.28.1 front end. 0068 only adds a table, so
  the old code runs on it.

## Deploying v0.28.1

A patch with the interval fixes, on the owner's ask (2026-11-18, "Add as a patch"): a stretch lying
half or more along a longer one ridden the same way is left out of the file, a path with more than
180 degrees of tight bends in 200 m is left out, and the hover card says its minutes as a rough
guess with the speed they assume, in Spanish too (#1347). The committed `intervals.json` already
has both rules applied (5,596 stretches); no PC build step.

**No `lua/`, `valhalla/`, `docker/`, requirements, migration, compose or nginx change, and the
lockfile's dependencies are those of v0.28.0**, so the beta's release agent takes it by itself; no
map rebuild, no router restart.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.28.1`, then approve).
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point, fast-forward the
  checkout, `docker compose build api`, recreate api and worker with no job todo or doing, then the
  front end.
- [ ] **Beta.** The release agent deploys it; `auto-release.sh status` shows it.
- [ ] **Beta check.** The app says 0.28.1; Plan, Interval stretches at Hains Point shows one
  stretch, Ohio Drive, one way (arrows), with no sidepath stretch beside it; the Mount Vernon Trail
  from Daingerfield Island north toward the airport has none; the hover card reads "a rough guess
  at ... mph".
- [ ] **Rollback.** The `pre-rel` api image and the v0.28.0 front end.

## Deploying v0.28.0

The release train's v0.28.0: Plan's chart docked under the map with click-to-centre and "Try to
avoid this stretch" (#1338), keyboard shortcuts with a ? sheet (#1336), saved routes with a
sketch and figures (#1337), Go's search naming the station and the stress bar's worst stretch
(#1335), an earlier first cue for a hard left off a road rated 3+ (#1332), steep-pitch marks for
Cargo, Tandem and E-bike (#1331), Ride on cheap phones (#1341), Ride loaded on first use (#1333),
route warnings in the rider's language (#1342), up to 200 points with course exports split only
when a device needs it (#1340), and the Interval stretches by minutes, shaded by length, with a
hover card, bollards counted and winding paths left out (#1322, #1324, #1328, #1343), with the
file rebuilt on the PC on 2026-11-18 (5,614 stretches). Junction ratings and Virginia stay out.

What changes for a deploy:

- two migrations: `0066_stress_suggestion_pk_tiebreak` and `0067_saved_route_figures` (a
  nullable JSON column on saved routes);
- every `valhalla/*.json`: `service_limits` `max_locations` 50 to 210 (bicycle, pedestrian,
  bikeshare) for #1340. A runtime setting only: the routers restart, no map rebuild. A plan of
  more than 50 points may fail at the router until they have;
- the front end: the lockfile changes and Ride is its own chunk (first load about 923 KB);
- no `lua/`, compose, nginx or Dockerfile change, so the beta's release agent takes a tag made by
  the Release workflow by itself, migrations and router restart included.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.28.0`, then approve).
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point, fast-forward the
  checkout, `docker compose build api`, recreate api and worker with no job todo or doing
  (migrations run), restart the routers, then the front end.
- [ ] **Beta.** The release agent deploys it; `auto-release.sh status` shows the routers restarted.
- [ ] **Beta check.** The app says 0.28.0; plan a route with 60 to 100 points (past the old router cap of 50), save it, reopen it;
  Plan's chart sits under the map; Interval stretches shows Klingle Valley Trail. Then a 200-point
  plan on a trail ride type (Mountain bike or Gravel) while `docker stats` runs on the beta host:
  the routers' 320M limits hold (no router restarted or killed for memory), and the plan answers
  or is refused with a message, never a 502.
- [ ] **Rollback.** The `pre-rel` api image, the v0.27.3 front end, and the old `valhalla/*.json`
  (the routers restart again). 0066 changes no schema and 0067 adds a nullable column, so the old code runs on them.

## Deploying v0.27.3

A patch with everything merged into release/v0.28.0 since v0.27.2, on the owner's ask (2026-11-17,
"Release everything in flight as a patch"): a jog along one way said in directions (#1310), a
re-route sends via points at the planned line's place for them (#1312), a stop or via point passed
within 50 m and left counts as reached (#1313), Interval stretches beside Climbs in Plan's "Trails,
terrain and training" (#1314), six riding icons for stops and notes (#1315, #1316) and the NOVA
park-closure link (#1302). Virginia prep (#1279) and the held rating work stay out.

**No `lua/`, `valhalla/`, `docker/`, requirements, migration, compose or nginx change, and the
lockfile's dependencies are those of v0.27.2** (same lock hash), so the beta's release agent takes
it by itself; no map rebuild, no router restart.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: the Release workflow
  (Actions, "Release", Run workflow on main, version `v0.27.3`, then approve), or an annotated tag
  v0.27.3 on that commit pushed from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point, fast-forward the
  checkout, `docker compose build api`, recreate api and worker with no job todo or doing, then the
  front end.
- [ ] **Beta.** The release agent deploys it; `auto-release.sh status` shows it.
- [ ] **Beta check.** The app says 0.27.3; Plan, Map layers, "Trails, terrain and training" holds
  Interval stretches beside Climbs; a stop's icon list has the six new icons.
- [ ] **Rollback.** The `pre-rel` api image and the v0.27.2 front end.

## Deploying v0.27.2

A patch with the Interval stretches layer, on the owner's ask (2026-11-16, "Add as a patch then"):
Plan's "Interval stretches" switch (#1304), its docs (#1305) and the first file, 2,871 stretches
written on the PC from the 2026-11-15 map (#1306); the api's `GET /api/intervals-near` and the
connector's `intervals_near` read the same file. Everything else on release/v0.28.0 stays there.

**No `lua/`, `valhalla/`, requirements, migration, compose or nginx change.** What changes for a deploy:

- the front end: the switch and a lazy-loaded `intervals.json` (about 1.1 MB, its own hashed file,
  fetched only when the switch is turned on, left out of the service worker's precache);
- the api image: `docker/api.Dockerfile` copies `frontend/src/interval-data/intervals.json` in, and
  the api answers `/api/intervals-near` (rate-limited as the other `_near` endpoints). The
  Dockerfile change makes the release agent's gate stop unless the tag names a CI-built image.
- nothing for the map: the file is already written. A map rebuild does not write it again by
  itself: after one, run `build_intervals` by hand and commit the file ("The Intervals layer"),
  or the stretches stay one map behind.

v0.27.1 must be on the beta first (its nginx template is a hand step). After that the beta takes
v0.27.2 by itself if the tag is made by the Release workflow (it names the api image it built, so
the Dockerfile change is deployed); a tag pushed by hand from the PC holds for a hand ship.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`: either the Release
  workflow (Actions, "Release", Run workflow on main, version v0.27.2, then approve), or an
  annotated tag v0.27.2 on that commit pushed from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point (tag the running
  api and pipeline images `pre-rel-<short>`, keep `index.html`), fast-forward the checkout,
  `docker compose build api`, then `docker compose up -d --no-deps --no-build --force-recreate api
  worker` with no job todo or doing, then the front end. No router restart, no map rebuild.
- [ ] **Beta.** With a Release-workflow tag, the release agent deploys it; `auto-release.sh status`
  shows it. With a hand-pushed tag: `auto-release.sh pause --wait "shipping by hand"`, then
  docs/BETA-RUNBOOK.md "Shipping an update later" at the tag (the api image built there, the worker
  recreated, the front end built on the PC), `smoke-test.sh --local`, `smoke-test.sh --public <url>
  --open`, `"$RM_SRC/scripts/beta/auto-release.sh" mark-deployed v0.27.2` and `auto-release.sh
  resume`.
- [ ] **Beta check.** `GET /api/intervals-near?lat=38.98&lon=-77.10` lists stretches (not 503);
  Plan, Map layers, Interval stretches draws the pink glow; the connector's `intervals_near` answers.
- [ ] **Rollback.** The `pre-rel` api image and the v0.27.1 front end.

## Deploying v0.27.1

A patch with the fixes finished for v0.28.0, on the owner's ask (2026-11-16): Map for no signal's
popout with a map of the areas (#1296); Ride's "Next stop" and no early arrival on transit trips
(#1292); a bike-open sidewalk that is the only link between two trails (#1293, takes effect at the
next map rebuild); LTS 1, 1.5 and 2 as modest tiebreakers (#1290); a via point matching the way it
sits on (#1297); region packs built by every cloud install (#1294) and served by the beta's nginx
(#1295). The Virginia map (#1279) and the rating-data work (#1291) stay in v0.28.0.

**No `lua/`, `valhalla/`, requirements or migration change.** What changes for a deploy:

- the api: `GET /api/offline/packs` lists each pack's area (#1296); a new command
  `manage.py build_offline_packs`, and `import_cloud_build --confirm` builds the packs after its
  swap (#1294);
- the beta's nginx template: the `/offline-packs/` location aliases the file by a named capture
  (#1295). The beta was patched by hand on 2026-11-15; the ship re-renders it so the file matches;
- `src/pipeline/run.py` and `routemaker/facility.py` (#1293): only at the next map rebuild.
- the areas' new borders (#1296, "Region packs" below): the packs on the PC and the beta were
  built to the old borders, so they keep them until the next map build packs them again. Until
  then a ride near a moved border (Bowie, Laurel, Anne Arundel, the West Virginia panhandle) may
  open a pack that lacks the roads there and falls back to its own mile.

The nginx template stops the release agent's gate, so **the beta is a hand ship**.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`, the owner tags v0.27.1
  (annotated) on that commit, from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point (tag the running
  api and pipeline images `pre-rel-<short>`, keep `index.html`), fast-forward the checkout,
  `docker compose build api rebuild`, then `docker compose up -d --no-deps --no-build
  --force-recreate api worker rebuild` with no job todo or doing, then the front end. No router
  restart, no map rebuild. If the PC's map has no packs yet, `docker compose exec api python
  manage.py build_offline_packs`.
- [ ] **Beta** **(owner)**, by hand: `auto-release.sh pause --wait "shipping by hand"` and `status`
  (no `IN PROGRESS`), then docs/BETA-RUNBOOK.md "Shipping an update later" at the tag (the api image
  built there, the worker recreated, the front end built on the PC), with the nginx template
  re-rendered, `--diff "$NGINX_SITE"` (only the `/offline-packs/` capture, or nothing if the hand
  patch matches), installed, `sudo nginx -t && sudo nginx -s reload`. Then `smoke-test.sh --local`,
  `smoke-test.sh --public <url> --open`, `"$RM_SRC/scripts/beta/auto-release.sh" mark-deployed
  v0.27.1` and `auto-release.sh resume`.
- [ ] **Beta check.** `GET /api/offline/packs` lists the packs with their areas; Settings, Riding,
  Map for no signal, Manage shows the areas' map, and one area downloads.
- [ ] **Spot checks.** Plan with a via point on a road beside a trail (Sligo Creek Parkway): the
  route rides the road. A transit trip in Ride says "Next stop" after leaving a stop.
- [ ] **Rollback.** The `pre-rel` api and pipeline images and the v0.27.0 front end. The nginx
  capture can stay (it serves the same files). On the beta, the images and `index.html` alone.

## Deploying v0.27.0

The road panel's big coloured level with its why and facts (#1258), its Setting line (#1259) and
pavement row; data dates in Settings About and places refreshed at every rebuild (#1237); Plan's
Keep to compare and One way / Loop / Out and back (#1238); Plan's Leave at (#1239); the connector's
parallel calls, prompts and "why this way" (#1234); foundations: rendered tests, a size budget,
parts loaded on first use (#1235); anonymous daily usage totals (#1261, #1273); route surface at a
glance (#1264); iPhone riders' steps (#1262); Check a route's busiest stretches (#1233); a live feed
that answers but stopped making sense (#1263); the calm search on long rides (#1231); Cargo and
Tandem barrier marks to go round (#1271); sign in with Discord, Google or Apple (#1270); off-grid
region packs, server and phone (#1232, #1265); the phone in a pocket (#1236); protest closures as
ordinary closures (#1252); closed-site and green-place labels (#1253, #1256, #1257); `osm_edit`'s
`motor_vehicle` tags (#1260); the privacy policy's required parts (#1243).

**No `lua/`, `valhalla/` or requirements change.** What changes for a deploy:

- migrations 0064 (`DailyUsage`, a new table: day, tool, count) and 0065 (sign-in identities: a
  new `SignInIdentity` table, and `User.discord_user_id` made nullable for accounts made with Google or
  Apple);
- a new middleware, `core.usage.UsageMiddleware`, counting a successful answer per tool per day,
  and new endpoints: `GET /api/offline/packs` (30 a minute, our default; `503 not_built` until the
  next map rebuild), `POST /api/usage` (10 a minute, our default), and `auth/sign-in`,
  `auth/sign-ins`, `auth/unlink`, `auth/google/*`, `auth/apple/*`, all through `location /`;
- `compose.yaml`: optional api settings `GOOGLE_*`, `APPLE_*` (unset: only Discord is offered) and
  `PRIVACY_OPERATOR` (unset: the privacy page names nobody); Caddy mounts `${DATA_ROOT}/tiles`
  read-only for `/offline-packs/*`;
- the beta's nginx template: a `/offline-packs/` location for the region packs;
- `scripts/beta/` (`ship-data.sh`, `receive-data.sh`: a new `packs` part, sent only once a
  rebuild has built them);
- pipeline changes that take effect only at the next map rebuild, in its own thread: the region
  packs (`pipeline/offline_packs.py`), the segment table's Setting and pavement columns (the road
  panel reads them only where the live table has them), and `setting.json` from the Census files
  (docs/OPERATIONS.md, "The road panel's Setting line");
- the Android app: the lock-screen turn card, tone and buzz need a new app build; the web app
  rides as before without it.

The release agent's gate stops on this tag (the compose mount, the nginx template, and
`src/pipeline/schema.py`), so **the beta is a hand ship**. The schema reason asks for no map ship
with this release: the road panel reads the new Setting and pavement columns only where the live
table has them, so they arrive with the next map rebuild and its data ship.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`, the owner tags v0.27.0
  (annotated) on that commit, from the PC.
- [ ] **Migrations.** 0064 adds a table. 0065 adds a table and drops `NOT NULL` from
  `User.discord_user_id`: the v0.26.0 api never writes a null there and reads accounts as before. Both
  reversible while no account was made with Google or Apple (0065 backwards fails on a null
  `discord_user_id`; no such account exists until those keys are set).
- [ ] **At home**, as "Deploying a planner and front-end release", before the weekly rebuild
  (Tuesday 08:00 UTC) or with it paused, and not between 07:00 and 07:30 UTC: rollback point (tag
  the running api and pipeline images `pre-rel-<short>`, keep `index.html`), fast-forward the
  checkout, `docker compose build api rebuild`, `migrate`, then `docker compose up -d --no-deps --no-build --force-recreate api
  worker rebuild caddy` with no job todo or doing (caddy for the new mount), then the front end.
  No router restart, no map rebuild.
- [ ] **Beta** **(owner)**, by hand: `auto-release.sh pause --wait "shipping by hand"` and `status`
  (no `IN PROGRESS`), then docs/BETA-RUNBOOK.md "Shipping an update later" at the tag (the api image
  built there, `migrate`, the worker recreated, the front end built on the PC), with the nginx
  template re-rendered, `--diff "$NGINX_SITE"`, installed, `sudo nginx -t && sudo nginx -s reload`
  (as in "A new release sha", step 9). `PRIVACY_OPERATOR=` with the owner's name in `.env` by hand
  (BETA-RUNBOOK's settings table), then `beta-compose.sh up -d api`. Then `smoke-test.sh --local`,
  `smoke-test.sh --public <url> --open`, `"$RM_SRC/scripts/beta/auto-release.sh" mark-deployed
  v0.27.0`, `"$RM_SRC/scripts/beta/auto-release.sh" install` (a hand ship does not refresh the
  agent's own copy of `receive-data.sh`, which v0.27.0 changes), and `auto-release.sh resume`.
- [ ] **Beta check.** `/privacy` names the operator in Contact; `GET /api/offline/packs` answers
  `503 not_built` and Settings' "Map for no signal" says it needs a signal or lists none until the
  next rebuild; Settings About shows the map data's dates; signing in offers Discord alone until
  Google or Apple keys are set (each needs its outbound host: `accounts.google.com`,
  `oauth2.googleapis.com`, `appleid.apple.com`).
- [ ] **Spot checks.** Tap a road: the big coloured level with its why, and the facts with their
  sources. Plan: Keep, then a second route shows the compare table; Out and back comes back the
  same way; When's Leave at takes a day and time. Open a GPX in Check a route: its busiest
  stretches each offer Use this way. A route shows its paved, gravel and dirt miles.
- [ ] **Rollback.** The `pre-rel` api and pipeline images (`--force-recreate api worker rebuild`)
  and the v0.26.0 front end. The usage table and the identities table stay (the v0.26.0 api ignores them). The nginx
  `/offline-packs/` location can stay. On the beta, the images and `index.html` alone: no
  `restore-dump`.

## Deploying v0.26.0

The first wave: My routes in its own window (#1168), archived assistant test drafts (#1169), sudden
closures from AlertDC with Ride's closure window (#1175), closed sites shaded and routed to their
gate with the big parks named (#1173, data #1199), and three override files: Whip-poor-will Way
(#1170), the Patuxent Research Refuge's closed area (#1172), and quieter side streets with the
Arlington comfort index (#1174). The backlog of 2026-11-12, which the owner put in this release:
the route scorecard (#1179), off-grid riding and its offline way back (#1180, #1192), ratings kept
true with an evidence grade (#1183), the ride summary's lines (#1184), Go's first screen (#1185),
the cue bench (#1187), barriers on Cargo and Tandem routes (#1188, list #1210), Montgomery County
and park trail closures (#1189, #1198, #1201), small fixes (#1191, #1208), bike loops (#1193),
releases without the PC (#1195), testers' alerts, status line, Send feedback and battery line
(#1197), and fewer turns, with the turn charge at every setting on the owner's yes (#1200, #1207).

**No `lua/`, `valhalla/` or requirements change.** What changes for a deploy:

- migrations 0062 (`ConnectorDraft.archived_at`, a nullable column) and 0063 (the review queue's
  new "Facts changed since rated" choice, no column change);
- a new worker task, `refresh_alertdc`, every minute (its alert window 10 minutes,
  `runs.STALE_AFTER`), reading the same AlertDC host as before;
- one new outbound host, `www7.montgomerycountymd.gov` (443), for `refresh_dc_closures` (#1189);
- new endpoints: `GET /api/closures/stamp` (20 a minute per address, our default),
  `POST /api/offline/network` (12 a minute, our default; `503 not_built` until the next rebuild),
  `POST /api/route/loop-shapes` (counts 3 on the routing limit and takes one of the routing
  slots), and `GET`/`POST /api/feedback` (sending: 5 an hour per client, 60 an hour in all), all through
  `location /` like the rest of `/api/`. Feedback is posted by the api to `discord.com`, so on a
  filtered beta the api needs that host even without Discord sign-in;
- `compose.yaml`: one optional secret for the api, `FEEDBACK_WEBHOOK_URL` (unset: no Send
  feedback entry);
- the beta's nginx template (#1197, #1191): a `/status.json` location for the riders' status line,
  gzip level 6, and the map's glyphs compressed;
- `docker/api.Dockerfile`: `restricted-sites.json` and `trail-miles.json` copied in, so the beta
  agent's gate stops on the tag and **the beta is a hand ship**;
- `scripts/beta/` (`alert.sh`, `auto-release.sh`, `cd_logic.py`), refreshed by the ship but not
  reinstalled;
- pipeline changes that take effect only at the next map rebuild, in its own thread: the side-path
  step (#1174, #1190), `{schema}.offline_way` (#1192) and the rated-facts report (#1183);
- the Android app: the battery line needs a new app build; nothing on the server waits for it.

The closed sites file is built and committed (#1199: 144 sites, 63 labels, 582 gates), and the
barrier list too (#1210: 11,734 barriers from the 2026-11-02 extract). Neither is an owner step
before the tag.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`, the owner tags v0.26.0
  (annotated) on that commit, from the PC. The new Release workflow (#1195) does not apply yet:
  it needs its one-time setup (docs/BETA-RUNBOOK.md, "The release workflow"), and the beta is a
  hand ship this time anyway.
- [ ] **Outbound host.** Add `www7.montgomerycountymd.gov` (443) to beta's egress list, and
  home's if it is filtered: the worker's `refresh_dc_closures` now reads Montgomery County DOT's
  road closures (source `moco`, routed round as `sha` is); with no good read in 45 minutes the run
  fails. The same run also fails at once with "read as nothing: <source>" where a usually busy
  source parses to nothing (its last copy kept). The park agencies' trail closures (`park_alert`)
  are a hand-read file in the release (two entered: the W&OD crosswalk detour, Nov 17-24, and the
  C&O at Dam No. 5): nothing to deploy for them.
- [ ] **Migrations.** 0062 adds a nullable column with no default: the v0.25.1 api inserts drafts
  without it (null, listed) in the minutes between `migrate` and its recreation, and after a
  rollback of the images, and never reads it. 0063 changes choices only. Both reversible.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point (tag the running
  api image `pre-rel-<short>`, keep `index.html`), fast-forward the checkout, `docker compose build
  api rebuild` (tag the pipeline image `pre-rel-<short>` too: the rebuild's calm-road sentinel moved
  to way 11507801, #1172, and a v0.25.1 `rebuild` image still checks way 86073896, which the closed
  area file closes), `migrate`, then `docker compose up -d --no-deps --no-build --force-recreate api
  worker rebuild` with no job todo or doing, then the front end. No router restart, no map rebuild.
- [ ] **Beta** **(owner)**, by hand: `auto-release.sh pause --wait "shipping by hand"` and `status`
  (no `IN PROGRESS`), then docs/BETA-RUNBOOK.md "Shipping an update later" at the tag (the api image
  built there, `migrate`, the worker recreated so it picks up `refresh_alertdc`, the front end built
  on the PC). Before the smoke test, the three one-time steps of BETA-RUNBOOK "Alerts" (#1197):
  `rm_absent "$RM_DATA/status" && sudo install -d -m 755 -o "$(id -un)" -g "$(id -gn)" "$RM_DATA/status"`
  (the data root is root's, and the login user's agent and alert.sh write the file); the nginx template re-rendered,
  `--diff "$NGINX_SITE"`, installed, `sudo nginx -t && sudo nginx -s reload` (as in "A new release
  sha", step 9); and, when the owner has the bug-reports forum's webhook, `FEEDBACK_WEBHOOK_URL=` in
  `.env` and `beta-compose.sh up -d api`. Then `smoke-test.sh --local`, then `smoke-test.sh --public
  <url> --open` (no site password since 2026-10-22), then `"$RM_SRC/scripts/beta/auto-release.sh" mark-deployed v0.26.0`
  (the new script's, not the installed v0.25.x copy's: only the new one records v0.25.1 as the
  release `rollback` puts back), then
  `"$RM_SRC/scripts/beta/auto-release.sh" install` (a hand ship does not reinstall the agent, and
  v0.26.0 changes it: #1195's quick deploys, `rollback`, `rollback-map`, `ship-held` and the
  workflow image pull start with the next release), then `"$RM_SRC/scripts/beta/alert.sh" install`
  (#1179's nightly scorecard, 3 AM ET, report only, and #1197's new checks: the ship refreshes the
  script, not its timers; the checkout's copy, because `install` copies itself into `cd/bin` and the
  `cd/bin` copy stops with "are the same file"), then `auto-release.sh resume`.
- [ ] **Beta check.** Within five minutes, `runs` shows `refresh_alertdc` succeeding each minute
  with detail `alertdc N closures, M notices` or `alertdc unchanged`; a detail of `alertdc failed`
  means the host is not answering (the run itself only fails after 45 minutes), and the next
  `refresh_dc_closures` succeeds with the new host. `GET /api/closures/stamp` answers 200 (a group
  of more than 20 riders on one Wi-Fi gets some 429s, which the app skips until the next minute);
  `GET /status.json` answers 404 when all is well (if it reads "trails" for good, the
  watch's trail check is failing, for example on the Road Bike router the agent leaves stopped on
  a host short of memory: set `RM_ALERT_TRAILS=0` and say so in the thread); `POST /api/offline/network` answers `503
  not_built` until the next map rebuild, and Ride rides as before. The AlertDC parser was written
  from a made-up sample: when the live list next carries a police or crash road item, check that it
  shows as a closure (the map, the road panel) with the title "Police activity: streets closed
  near ..." for police items.
- [ ] **The three override files** (optional, separate, each on the owner's go). On the PC with
  `load_access_overrides`, a dry run each, then `--confirm` with the owner's go per file:
  `2026-11-12-owner-patuxent-whip-poor-will-way.json`, `2026-11-12-owner-patuxent-closed-area.json`,
  `2026-11-12-owner-side-streets-and-arlington-index.json` (12,396 rows, each retiring its own-picks
  row; if its dry run reports ways without fingerprints, run the fingerprint backfill first, as for
  the own-picks files). All take effect at the next map rebuild, in its own thread, not with this
  release. That rebuild also writes the offline road network and the rated-facts report, and
  checks the new sentinel way 11507801 (estimated, not yet measured on a build).
- [ ] **Spot checks.** Save & load: Save and Share at the top, My routes opens its own window with
  "Back to Save & load". Through the connector: a `plan_route` with `test: true` stays out of Load
  route, and `archive_draft` drops another. The map shades NASA Goddard with "No public access",
  and a route to a point inside it ends at a gate with "Restricted site. Route ends at the gate."
  Rock Creek Park, Greenbelt Park and the Patuxent Research Refuge have their names on the map,
  and the refuge's closed area is shaded. Go's first screen shows the warnings above the fold; a
  Plan bike loop from a start and a distance draws its shapes; a Cargo route past a known
  bollard names it.
- [ ] **Rollback.** The `pre-rel` api image (`--force-recreate api worker`) and the v0.25.1 front end.
  Leave `rebuild` on the v0.26.0 image: the `pre-rel` pipeline image still checks way 86073896, which
  the closed-area file closes once it is loaded. A police area already in the closures row is read by
  the v0.25.1 api as a line along its outline (routed round the edge) until it drops, at most 3 h.
  The `archived_at` column stays; on v0.25.1 archived drafts list again until they expire. The
  nginx `/status.json` location and the status directory can stay (404 with no file). On the beta,
  the images and `index.html` alone: no `restore-dump`, as 0062 and 0063 change no data.

## Deploying v0.25.1

Ride follows a parallel way beside the route instead of re-routing back (#1165): within about 500 ft
[150 m] of the line and going its way (our defaults, not measured). **Front end only** (`navigate.ts`,
`RideMode.tsx`), plus the version and the docs pages: no migration, no `docker/`, compose, `deploy/`,
`lua/`, `valhalla/` or `scripts/beta/` change, no map rebuild.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`, the owner tags v0.25.1
  (annotated) on that commit, from the PC.
- [ ] **Beta.** With v0.25.0 deployed there, the release agent's gate passes v0.25.1 and it deploys
  it by itself (the front end it builds, the api image rebuilt from an unchanged Dockerfile). If the
  beta is still on v0.24.0, the gate stops on `docker/api.Dockerfile` as for v0.25.0: ship v0.25.1
  by hand with "Deploying v0.25.0"'s beta steps at the v0.25.1 tag, then `mark-deployed v0.25.1`.
- [ ] **At home.** The front end at the tag ("Deploying a planner and front-end release").
- [ ] **Spot check.** On a ride, take a path beside the route for a block: Ride says "Off the planned
  route." once, calls no turns and does not re-route; turn cues pick up where the ways meet.
- [ ] **Rollback.** The v0.25.0 front end.

## Deploying v0.25.0

Fixed saved routes (#1146, #1148, #1150), route notes and stop icons (#1154, #1155), phone cue
images with arrows (#1152, #1153), the connector's route view, Mass Ride view and route picture
(#1141-#1143, #1145), the Bethesda Trolley Trail turn at Charles St (#1140), and the North Bethesda
bike lane overrides file (#1136). **No `lua/`, `valhalla/`, `src/pipeline/`, compose, Caddyfile,
nginx (`deploy/`) or requirements change, no new environment variable, worker, scheduled job or
outbound host, and no map rebuild.** One line in `docker/api.Dockerfile` copies
`mcp/route_view.html` into the api image, so the beta agent's gate stops on the tag
(`verdict=stop`) and the beta is a hand ship.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`, the owner tags v0.25.0
  (annotated) on that commit, from the PC.
- [ ] **Migration.** 0061 (`saved_route.fixed`, `saved_route_version.fixed`) adds two booleans with
  a database default of false: the v0.24.0 api keeps saving routes in the minutes between `migrate`
  and its recreation, and after a rollback of the images. Reversible.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point (tag the running
  api image `pre-rel-<short>`, keep `index.html`), fast-forward the checkout, `docker compose build
  api rebuild` (tag the pipeline image `pre-rel-<short>` too: the rebuild's calm-road sentinel moved
  to Wildlife Loop, #1144, and a v0.24.0 `rebuild` image still checks Gambrill Park Road, which the
  own picks rate 2.5, so its next run stops at that check), `migrate`, then `docker compose up -d
  --no-deps --no-build --force-recreate api worker rebuild` with no job todo or doing, then the front
  end. No router restart, no map rebuild.
- [ ] **Beta** **(owner)**, by hand: `auto-release.sh pause --wait "shipping by hand"` and `status`
  (no `IN PROGRESS`), then docs/BETA-RUNBOOK.md "Shipping an update later" at the tag (the api image
  built there, `migrate`, the front end built on the PC), `smoke-test.sh --local`, then
  `smoke-test.sh --public <url> --passwords-file <file>`, then `auto-release.sh mark-deployed
  v0.25.0` and `auto-release.sh resume`. The new `/mcp/gpx/<token>.png` and `-cues-N.png` links need
  no nginx or Caddy change: they go to the api through `location /`, and the access-log rule for
  `/mcp/gpx/` already takes their tokens out.
- [ ] **The North Bethesda override file** (optional, separate). `fixtures/overrides/2026-11-10-owner-north-bethesda-bike-lanes.json`
  is loaded on the PC with `load_access_overrides` (dry run, then `--confirm` with the owner's
  go); its rows take effect at the next map rebuild, not with this release. Its five Grand Park
  Avenue rows say "held until the owner checks it": ask the owner about them before the load.
- [ ] **Spot checks.** Plan: Save with Fixed route ticked, reopen it from Load route ("Fixed"), and
  Start ride: off the line, Ride shows the way back, never a new route. Add a caution note on the
  map: it shows on the map and in the cue sheet, and Ride says it as you reach it. Plan's GPX panel:
  the lock-screen cue image has arrows and a dark choice. On a ride along the Bethesda Trolley Trail
  southbound, Ride calls the turn at Charles St. Through the connector: plan a route, then open its
  picture link and one cue image link (each 200, `image/png`); the access logs show the path with
  its token taken out.
- [ ] **Rollback.** The `pre-rel` api image (`--force-recreate api worker`) and the v0.24.0 front end.
  The `fixed` columns stay (with their default); a fixed route opened on v0.24.0 is a via route. On
  the beta, the images and `index.html` alone: no `restore-dump` (it would lose routes saved since
  the ship), as 0061 only adds columns.

## Deploying v0.24.0

v0.24.0 ships with the map rebuilt from the own-picks files (the owner, 2026-11-10: "Ship with the
new map", and "Also push the new data out with it."), as one hand ship: `lua/` changed (#1126's free
wide gates), so the beta agent stops on the tag.

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`, the owner tags v0.24.0
  (annotated) on that commit, from the PC.
- [ ] **The own picks, before the map** **(owner)**. `fixtures/overrides/2026-11-09-owner-{md,va,wv}-own-picks.json`
  (222,844 stress rows) must be loaded on the PC (`load_access_overrides`, dry run first, then
  `--confirm` with the owner's go per file, detached, outside 07:00 UTC) before the cloud run is sent:
  the build reads only approved `Override` rows from the dump. A build sent before the load has the
  code but none of the picks, and says nothing.
- [ ] **The build's commit.** The map is built on the on-demand box (run cloud-20261110b) at
  `282481cb`, not at the tag: the v0.24.0 tree plus the calm-road sentinel change (Wildlife Loop
  for Gambrill Park Road, #1144; validation only). The first run, at `996b8614`, stopped at that
  check. `git diff --stat v0.24.0 282481cb` shows only `src/config/settings.py` and this file,
  and nothing touches `lua/`, `valhalla/`, `src/pipeline/`, `fixtures/` or
  `scripts/cloud/box-rebuild.sh`, so the install takes `--allow-sha-mismatch`, at home and with
  `--beta`.
- [ ] **Migrations.** 0059 (`connector_draft.root`, `saved_at`) and 0060 (`reviewed_closure.on_foot`)
  add nullable columns only; safe on the running map and reversible. Rolling the code back past
  v0.24.0 brings back the 24 h draft keep, so drafts 1-7 days old go at the next sweep.
- [ ] **Rollback points and images** **(owner)**, as "Deploying a planner and front-end release",
  then the import and swap of the cloud result (dry run first: read its "approved after the dump"
  list). No new environment variable, worker, scheduled job or outbound host.
- [ ] **Beta** **(owner)**, by hand: check out the tag, then `scripts/cloud/import-result.sh --beta
  --allow-sha-mismatch [--swap] <RUN_URL>`, `migrate`, the front end built on the PC
  (`ship-data.sh`), `smoke-test.sh --local --trails`, then `--public`.
- [ ] **The Climbs layer** (optional). `climbs.json` (#1116) was built from 20261109T111715Z; a
  `build_climbs` on the new map after the swap is optional.
- [ ] **The open data download**, after the swap, as "The open data download (after a map swap)":
  the export is shown to the owner before the data release is uploaded.
- [ ] **Spot checks.** A Tandem or Cargo route through a plain wide gate (no access, width or
  motor-vehicle tags) takes it with no gap charge; a Mass Ride near H Street NE keeps off the
  streetcar rails; Load route (signed in) lists an assistant draft with Save and Delete.
- [ ] **Rollback.** The `pre-rel` api image and the v0.23.0 front end; the map's own rollback
  (`rollback_rebuild`) puts back 20261109T111715Z. The own-pick rows stay in the database.

## Deploying v0.23.0

- [ ] **The tag** **(owner)**. Once `test` and `a11y` are green on `main`, the owner tags v0.23.0
  (annotated) on that commit, from the PC.
- [ ] **The build's commit.** The v0.23.0 map is built on the cloud box at `afb3f6a6` (release/v0.23.0's
  head when the run was sent, 2026-11-09), not at the tag. Nothing after it touches `lua/`,
  `valhalla/`, `src/pipeline/` or `scripts/cloud/box-rebuild.sh` (check:
  `git diff --stat afb3f6a6 v0.23.0 -- lua valhalla src/pipeline scripts/cloud/box-rebuild.sh` is
  empty), so the install takes `--allow-sha-mismatch`, at home and with `--beta` (it is passed on to
  `receive-data.sh`).
- [ ] **Rollback points and images, before the map** **(owner)**, as "Deploying a planner and
  front-end release", out of 07:00-07:30 UTC and with no rebuild job todo or doing: tag the running
  api **and pipeline** images `pre-rel-<short>`, fast-forward the checkout, `docker compose build api
  rebuild`, then `docker compose up -d --no-deps --no-build --force-recreate api worker rebuild`. The
  import runs `import_cloud_build` in the `rebuild` container: an older image knows seven graphs, so
  `paved-weekend` would be unpacked but never promoted, with no error. The front end goes last, after
  the swap: before it, every weekend Road Bike ride says there is no weekend road bike map.
- [ ] **The weekly rebuild.** Import and swap the cloud build before the next Tuesday 08:00 UTC
  (3:00 AM ET) rebuild, or pause it (`WEEKLY_REBUILD_PAUSED`) for the run: a rebuild here resets the
  staging schema an install restored, and `lua/` is mounted from the checkout.
- [ ] **Caddy.** The Caddyfile adds `/tandem` (the Tandem ride type): validate it in a throwaway
  container and recreate caddy alone ("Applying a Caddyfile change"). On beta the nginx template
  adds it too: re-render it with the release. Check: `curl -sI https://<site>/tandem` is a 302 to
  `/#preset=tandem`. Tandem is costing only: no graph, no map rebuild.
- [ ] **Android.** The app's link list adds `/tandem`; it opens in the app only from the next
  Android build.

### Road Bike's weekend graph (ships with the next map rebuild)

The owner, 2026-11-08: "Road bikes absolutely use those parkways on the weekends. It's probably
their most common destination."; "New weekend graph" (the graph and its costs: "Road Bike's
weekend graph", in "Paths bicycles may not ride (NO-BIKE-PATHS)" below). An eighth graph and router, so it ships with
the next map rebuild, built at a commit that has it: until then a weekend Road Bike ride plans on
the paved graph as before. `src/pipeline/`, `valhalla/` and both compose files changed, so the
beta agent stops on the tag and the beta deploy is by hand, with the data bundle. No migration,
no new environment variable to set (`VALHALLA_PAVED_WEEKEND_URL` has its default), no new
outbound host or scheduled job. With `</dev/null` on every docker command:

- [ ] **The data directory** **(owner)**, at home and on the PC: `sudo sh scripts/prepare_data_root.sh
  --env-file ./.env` (it adds `tiles/paved-weekend` and `tiles/paved-weekend/current`, owned
  10001). Never name `valhalla-paved-weekend` in an `up` before its first build: Docker would make
  the directory as root, which the rebuild cannot write.
- [ ] **The default routers' new limit**, **(owner)** on the PC. compose.yaml lowers `valhalla-standard`,
  `valhalla-no-trail`, `valhalla-ebike` and `valhalla-weekend` from 2G to 1856M: after the
  checkout moves, `python3 scripts/check_compose_limits.py compose.yaml` (swap-time peak 32.0G),
  then `docker compose up -d --no-deps --no-build valhalla-standard valhalla-no-trail
  valhalla-ebike valhalla-weekend` recreates them on the new limit.
- [ ] **The map**, at the tagged commit: the cloud box (`--beta-bundle` for the beta) or
  `run_rebuild_now`. Eight graphs: about 20-25 minutes longer than seven, one extract more, about
  1.1 GB more per kept build; the cloud result's `tiles-paved-weekend.tar` (a result without it is
  refused). Then swap. **(owner)**: the rebuild and the swap.
- [ ] **The routers**, at home and on the PC, **(owner)** on the PC. Restart the four. Where the `offroad` profile runs,
  start the new one once: `docker compose --profile offroad up -d --no-deps --no-build
  valhalla-paved-weekend` (it needs about 0.75 GB spare: check memory inside WSL on the PC first);
  until it has a container, a `restart` that names it restarts none of the others on the line.
  Then `docker compose --profile offroad restart valhalla-offroad valhalla-mtb valhalla-paved
  valhalla-paved-weekend` and `docker compose exec -T api ./manage.py sync_upstreams`. Where it is
  not started, a weekend Road Bike ride plans on the paved graph and says the parkways were lost.
- [ ] **The Climbs layer**, after the swap: `flock <heavy.lock> docker compose exec -T rebuild
  ./manage.py build_climbs </dev/null` (hills fixes, #1060: bridges and tunnels found in the extract
  are levelled), then commit the new climbs file as "The Climbs layer" says.
- [ ] **The transit schedule** (#1058's timetable end), at the next timetable refresh or now:
  `scripts/build_transit_schedule.py` as in "Transit schedule (TRANSIT-ASSIST, v0.6.0)", and on the
  beta with its data. No map rebuild.
- [ ] **The boot unit** **(owner)**, where it is installed: `scripts/boot/start-stack.sh` now starts a fourth
  trail router, so its unit's `TimeoutStartSec` went from 6000 to 6300 s (the worst case is 6005 s):
  `scripts/boot/install-boot-unit.sh install` again from the new checkout.
- [ ] **Beta** **(owner)**, by hand, "A new release sha" with the data bundle (docs/BETA-RUNBOOK.md):
  - The memory check first: `free -m` "available" plus the resident memory of this project's
    running containers at least 8806 MiB (the 8406 MiB startup peak with both Road Bike routers
    plus 0.39 GiB). Under it, ship as below but leave `valhalla-paved-weekend` stopped; the agent
    does the same check and leaves it stopped with a warning.
  - Check out the tag, set `TAG=`, `"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file
    .env` ("beta compose: ok", 7.96 GiB resident).
  - Data: `receive-data.sh verify`, `db --update-data --stage-only`, `sudo ... files` (installs
    `tiles/paved-weekend`), `sudo ... db --update-data` (not during the 07:00 UTC backup).
  - Restart the four routers one at a time; then
    `scripts/beta/beta-compose.sh up -d --force-recreate valhalla-offroad valhalla-mtb valhalla-paved valhalla-paved-weekend`
    (leave out `valhalla-paved-weekend` if memory was short); `sync_upstreams`.
  - Or, from the cloud run's bundle: `scripts/cloud/import-result.sh --beta --allow-sha-mismatch
    [--swap] <RUN_URL>`. It applies the same memory check before starting `valhalla-paved` or
    `valhalla-paved-weekend` and leaves a stopped one stopped, with a warning, when it is short.
  - `smoke-test.sh --local --trails` (now checks a weekend `road-bike` ride on the
    `paved-weekend` graph, and a weekday one on `paved`), then `--public`. The weekend check is
    skipped, with a `SKIP` line, while `valhalla-paved-weekend` is stopped (memory short); since
    v0.26.0 the weekday one is likewise skipped while `valhalla-paved` is stopped.
  - The agent and router hook changed: `scripts/beta/auto-release.sh install` and, where
    installed, `scripts/beta/restart-routers.sh install`, from the new checkout, after
    `mark-deployed`; then `resume`.
- [ ] **Spot checks.** A Road Bike route at the weekend ride time answers `"variant":
  "paved-weekend"` and rides Beach Drive or Sligo Creek Parkway where they are the calm way; the
  same trip on a weekday answers `"paved"` and keeps off them where the traffic says so.
- [ ] **Rollback.** After the first rebuild with it, `rollback_rebuild` withdraws `paved-weekend`
  (its first build) and stops `valhalla-paved-weekend`; weekend Road Bike rides then plan on the
  paved graph. Rolling the code back to a release without it: first
  `docker compose --profile offroad stop valhalla-paved-weekend` (on the beta
  `scripts/beta/beta-compose.sh stop valhalla-paved-weekend`): the older compose files have no
  such service and their budgets do not count it.

## Deploying v0.22.3

A patch for the post page's photos (v0.22.2, #1067): on the beta the photo on a post's route map was
a dark circle and its pop-out a blank box, because the map's rules for its own preview picture also
hid and resized the photo pictures inside the live map. Those rules now reach only the map's own
picture. Each photo is now a small dot on the route with a short line to its thumbnail, set beside the
route so the trail stays visible, on the route map and on the highlight maps. **`src/core/route_posts.py`
and the post page's script (`frontend/src/post/`)**, with the version in `pyproject.toml`,
`src/routemaker/__init__.py`, `frontend/package.json`, `README.md`, and the docs pages rebuilt with
`DOCS_RELEASE=0.22.3` (version stamps only). **No migration, no `src/pipeline/`, `lua/`,
`valhalla/*.json`, compose, Caddyfile, nginx, Dockerfile, requirements, `mcp/` or `mobile/` change, no
new environment variable, scheduled job or outbound host, and no map rebuild.**

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.22.3 (annotated) on
  that commit, from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point (tag the running api
  image `pre-rel-<short>`, keep `index.html`), fast-forward the checkout, `docker compose build api`,
  then `docker compose up -d --no-deps --no-build --force-recreate api worker` with no job todo or
  doing, then the front end (the post page's script). No migration, no router restart.
- [ ] **Beta, by its agent**, once its deployed tag (`$RM_STATE/cd/deployed-tag`) is v0.22.2: the gate
  sees `src/core/`, `frontend/` and the version files, none of them a stop, and deploys in one pass.
  Stuck: `git fetch --force --tags origin`, then `scripts/beta/auto-release.sh retry v0.22.3`.
- [ ] **Spot checks.** On a post with located photos, each photo shows its picture (not a dark circle):
  a dot on the route and the thumbnail beside it, clear of the line, on the route map and on any
  highlight map it falls in. Tap the thumbnail: the pop-out shows the photo and caption beside the
  route. Escape closes it and the focus returns to the thumbnail.
- [ ] **Rollback.** The `pre-rel` api image (`--force-recreate api worker`) and the v0.22.2 front end.
  Nothing in the database or the map changes. On the beta: the agent rolls back by itself on a failed
  pass; later, rollback C, then `auto-release.sh hold v0.22.3`.

## Deploying v0.22.2

A patch for Featured routes: each card on the list (`/routes/`) shows the map on top, full width,
with the words below, and the route's preview picture shows only its map part (its word band repeated
the card's words) (#1052); a post's photos with a spot are round thumbnails on its route map that open
a pop-out, and small thumbnails on the highlight maps they fall in (#1067). **`src/core/route_posts.py`
and the post page's script (`frontend/src/post/`)**, with the version in `pyproject.toml`,
`src/routemaker/__init__.py`, `frontend/package.json`, `README.md`, and the docs pages rebuilt with
`DOCS_RELEASE=0.22.2` (version stamps and one sentence in Using RouteMaker). **No migration, no `src/pipeline/`, `lua/`,
`valhalla/*.json`, compose, Caddyfile, nginx, Dockerfile, requirements, `mcp/` or `mobile/` change, no
new environment variable, scheduled job or outbound host, and no map rebuild.**

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.22.2 (annotated) on
  that commit, from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point (tag the running api
  image `pre-rel-<short>`, keep `index.html`), fast-forward the checkout, `docker compose build api`,
  then `docker compose up -d --no-deps --no-build --force-recreate api worker` with no job todo or
  doing, then the front end (the post page's script). No migration, no router restart.
- [ ] **Beta, by its agent**, once its deployed tag (`$RM_STATE/cd/deployed-tag`) is v0.22.1: the gate
  sees `src/core/`, `frontend/` and the version files, none of them a stop, and deploys in one pass.
  Stuck: `git fetch --force --tags origin`, then `scripts/beta/auto-release.sh retry v0.22.2`.
- [ ] **Spot checks.** Open `/routes/` on a phone and a desktop: each card has the map on top, full
  width, no white text strip at its foot, the base map credit visible, and the name and figures below.
  On a post with located photos, each photo is a round thumbnail on the route map; Enter or a tap opens
  the photo and caption, Escape closes it and the focus returns to the thumbnail.
- [ ] **Rollback.** The `pre-rel` api image (`--force-recreate api worker`) and the v0.22.1 front end.
  Nothing in the database or the map changes. On the beta: the agent rolls back by itself on a failed
  pass; later, rollback C, then `auto-release.sh hold v0.22.2`.

## Deploying v0.22.1

A patch with the fixes the v0.22.0 review left for later: a Rebalance Ride's drop-off dock, chosen at
the pick-up dock, is kept with the ride left going, so Resume (and Undo after End ride) rides on to it
(#1047); mountain-bike trails on the dark ride panel's ribbon have a light edge (#1048); the drop-off
list is said as it arrives, the Load route tag chips wrap, and the assistant's photo upload link takes
the photo's spot from the `X-Photo-Lat` and `X-Photo-Lon` headers, never the query string (#1049).
**Front end, `src/core/route_posts.py` (the upload link) and the connector's `draft_route_post` text
(`mcp/`)**, with the version in `pyproject.toml`, `src/routemaker/__init__.py` and `README.md`, and the
docs pages rebuilt with `DOCS_RELEASE=0.22.1`. **No migration, no `src/pipeline/`, `lua/`,
`valhalla/*.json`, compose, Caddyfile, nginx, Dockerfile, requirements or `mobile/` change, no new
environment variable, scheduled job or outbound host, and no map rebuild.** Either order is safe: an
assistant still sending `?lat=&lon=` gets its photo kept with no spot (`located: false`).

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.22.1 (annotated) on
  that commit, from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": rollback point (tag the running api
  image `pre-rel-<short>`, keep `index.html`), fast-forward the checkout, `docker compose build api`,
  then `docker compose up -d --no-deps --no-build --force-recreate api worker` with no job todo or
  doing, then the front end. No migration, no router restart. The connector's text (`mcp/`) is
  copied into the api image, so the api rebuild ships it; nothing else to restart.
- [ ] **Beta, by its agent**, once its deployed tag (`$RM_STATE/cd/deployed-tag`) is v0.22.0: the gate
  sees `frontend/`, `src/core/`, `mcp/` and the version files, none of them a stop, and deploys the api
  and the front end in one pass, with no migration. Stuck: `git fetch --force --tags origin`, then
  `scripts/beta/auto-release.sh retry v0.22.1`.
- [ ] **Spot checks.** Rebalance Ride: at the crowded dock, pick a drop-off, then reload the page and
  press Resume: the ride goes on to that dock ("Dock at ..."), not back to the pick-up. In dark theme, a
  ride over a mountain-bike trail shows a light edge round the trail on the ribbon. In Load route with
  several tags and Large text on a phone, the tag chips wrap onto a second row.
- [ ] **Rollback.** The `pre-rel` api image (`--force-recreate api worker`) and the v0.22.0 front end.
  Nothing in the database or the map changes. On the beta: the agent rolls back by itself on a failed
  pass; later, rollback C, then `auto-release.sh hold v0.22.1`.

## Deploying v0.22.0

Saved routes' tags, Archive and last opened, with the connector's `organize_route` (#1021);
Rebalance Ride from a start alone, the drop-off dock chosen at the pick-up and the day's totals
(#1023); stops on Bikeshare Ride, each stop a new trip (#1019; Rebalance Ride, a start alone since
#1023, takes none); mountain-bike trails
by level on the ride ribbon and the route line, slim ride graphs and a quiet Resume within 2 hours
(#1025, #1034); a quieter opening view (#1016); Fairfax park trail closures (#1029: the watch and
the file, which ships with no closure, each waiting for the owner's confirmation); Featured routes
photos with where each was taken and the assistant's upload links (#1030); junction and ride cue
fixes (#1026, #1027, #1028, #1036); the beta agent's release-notes post
(#1039) and the riders' notes posted by the owner's bot with their pictures (#1041, #1042); the
worker closing maintenance jobs whose worker died mid-run (#1043); and "Same ride or a new one?" in every tab (#1012, #1013), the
ride rail on a small phone (#1015) and the ride graph tidy-ups (#1014).

**What changes for the host.** Migrations 0057 (`saved_route.tags`, `archived_at`, `opened_at`,
`replaced_by`; `connector_grant.organizes_routes`) and 0058 (`route_post_photo.lat`, `lon`): columns
only, the ones that are not nullable with a database default, so the v0.21.x api keeps working on
the migrated database. A new url, `routes/<slug>/photos/send/<token>` (the assistant's photo upload,
signed, in `core.route_posts`; on the beta it sits behind the site's password like every page, so
an assistant's upload there is refused with 401: the links work on the public site). `src/core/geodata/fcpa-closures.json` and `routemaker.fcpa` (read by
the api; `scripts/fcpa_alerts.py` is run by hand, "Fairfax park trail closures"). The api and the
front end change together: the new front end sends Bikeshare plans with stops and a
Rebalance plan with no destination, which the v0.21.x api refuses (400), so the front end goes up
only after the api, as always. The other way round is safe: a v0.21.x page still open, a link or a
saved Rebalance plan with a destination is planned by the new api from its start alone. **No `src/pipeline/`, `lua/`, `valhalla/*.json`, compose, Caddyfile,
nginx, Dockerfile, requirements or `mobile/` change, no tile `FORMAT_VERSION` change, no new
environment variable, scheduled job or outbound host for the stack, and no map rebuild** (the trail
levels come from the live map's `mtb_level`). The routers need no restart, and the pipeline image
need not be rebuilt. The beta agent's gate from v0.21.0 or later says `deploy`, with migrations.
At home, in order, with `</dev/null` on every docker command:

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.22.0 (annotated) on
  that commit, from the PC.
- [ ] **Rollback points and images**, as "Deploying a planner and front-end release", out of
  07:00-07:30 UTC: tag the running api image `pre-rel-<short>`, keep `index.html`, fast-forward the
  checkout, then `docker compose build api`.
- [ ] **The api.** `docker compose run --rm --no-deps migrate` (0057, 0058), then
  `docker compose up -d --no-deps --no-build --force-recreate api worker`, with no job todo or
  doing. No router restart, no pre-draw.
- [ ] **The front end**, last.
- [ ] **The connector.** A grant made before v0.22.0 has no `organize_route`; the owner reconnects
  RouteMaker in the assistant (claude.ai, Settings, Connectors) to give it the new permission.
- [ ] **Beta, by its agent**, once its deployed tag (`$RM_STATE/cd/deployed-tag`) is v0.21.0 or
  later: the gate says `deploy` with migrations; the agent snapshots the database first, migrates,
  builds the api and the front end and starts them in one pass. The agent itself changed (#1039: it
  posts the live release's notes when a newer tag is held or waiting); after the deploy it puts its
  own new files in `$RM_STATE/cd/bin` (the run log says "step: the release changed the agent"). Only
  if the log says "WARNING: the agent's files could not all be reinstalled", run
  `scripts/beta/auto-release.sh install` from the v0.22.0 checkout. The riders' notes are now posted
  by the owner's own bot (#1041), with its token already in `$RM_STATE/discord/bot-token` ("Tester
  reports"): once, store the changelog channel's id in `$RM_STATE/discord/changelog-channel` and run
  `auto-release.sh install` (BETA-RUNBOOK, "Release notes for riders"). Until then the agent falls
  back to the old release webhook while `$RM_STATE/release-webhook` is stored, and with neither
  nothing is posted. The pass that deploys v0.22.0 runs the agent of before it, so v0.22.0's own notes
  may still go by the webhook; the bot posts from the next pass on. Stuck: `git fetch --force --tags
  origin`, then `scripts/beta/auto-release.sh retry v0.22.0`.
- [ ] **Beta, by hand, if it is still on v0.20.0** (v0.21.0's hand ship not yet done): the gate from
  v0.20.0 stops on `src/pipeline/schema.py`, as at v0.21.0. Ship v0.22.0 by hand once, in place of
  v0.21.0's, as "Deploying v0.21.0" says (pause, snapshot `--label release`, `index.html`, check out
  the tag, `TAG=`, `check_beta_compose.py`, the api image, migrate (0056 to 0058), api and worker,
  the front end, `smoke-test.sh --local --trails` then `--public`), with the rebuilt transit
  schedule's `transit` part if it is ready. The agent changed since v0.20.0:
  `mark-deployed v0.22.0`, then `scripts/beta/auto-release.sh install`, then `resume`.
- [ ] **Stuck jobs (#1043).** Within 10 minutes of the worker's restart (on the beta too, once it runs v0.22.0), the old
  `refresh_dc_closures` rows from 2026-10-19 are closed as `aborted` (an audit row
  `close_orphaned_job` each) and the alert's stuck-job lines go. A `nightly_backup` or rebuild job
  is never closed this way ("Most of those clear themselves").
- [ ] **Spot checks.** Tag a saved route (Save, or My routes > More > Tags); in Load route, filter
  by that tag, then Archive another: it leaves the list, Undo brings it back, and it is under
  Archived. Rebalance Ride in Go plans from your location to the nearest crowded dock with no
  destination asked; at that dock the card offers up to 3 drop-off docks, and the end screen shows
  "Today's Rebalance Rides". A Bikeshare plan with one stop shows two trips. A ride on a
  mountain-bike trail (Patapsco, Rosaryville) colours the ribbon and the route line by the trail's
  level. Mid-ride, switch to another app and come back within 2 hours, press Resume: the same ride
  carries on, its figures kept, with no "Already done?". Zoomed out below 12, no route shields or
  area closures. On the public site, on a Featured route draft, an assistant's photo goes up by its
  link and keeps where it was taken ("Where it was taken" under it).
- [ ] **Rollback.** The `pre-rel` api image (`--force-recreate api worker`) and the v0.21.2 front end.
  Migrations 0057 and 0058 only add columns with defaults or nulls: the v0.21.2 api ignores them,
  so the database stays migrated (tags and archive marks made meanwhile are kept, unseen). On the
  beta: the agent rolls back by itself on a failed pass; later, or after a hand ship, rollback C
  (docs/BETA-RUNBOOK.md: the previous api image and front end; the `release` snapshot only if
  needed), then `auto-release.sh hold v0.22.0` so the agent does not deploy it again.

## Deploying v0.21.2

A patch with what release/v0.22.0 held on 2026-11-06: Help opens one big "Using RouteMaker" button to
the guides in place of its two lines (#1006); the beta notice's "Sign up to test here!" opens the
Android beta's how-to-join page, `/about/android-beta.html`, and sits beside a "Using RouteMaker"
button (#1006); the Stress ratings page compares our levels with four agencies' (#993, from the
2026-11-06 open data export). **Front end and docs pages only** (`frontend/`, `scripts/a11y/check.mjs`),
with the version in `pyproject.toml`, `src/routemaker/__init__.py` and `README.md`. **No migration, no
`src/` code change, no `src/pipeline/`, `lua/`, compose, Caddyfile, nginx, Dockerfile or requirements
change, no new environment variable, outbound host or scheduled job, no `mobile/` change and no map
rebuild.**

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.21.2 (annotated) on
  that commit, from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": fast-forward the checkout, then
  the front end. The api image need not be rebuilt (only its version string changes); rebuild it
  with `docker compose build api` and recreate `api worker` if the version shown should say 0.21.2.
- [ ] **Beta**, by its agent, as at v0.21.1: once its deployed tag (`$RM_STATE/cd/deployed-tag`) is
  v0.21.0 or v0.21.1, the gate sees `frontend/`, `scripts/a11y/check.mjs`, `pyproject.toml` and
  `src/routemaker/__init__.py` (docs and `.md` files are inert), none of them a stop, and deploys.
  While v0.21.0 is not yet marked deployed the agent stops here too: finish the v0.21.0 hand ship and
  `mark-deployed v0.21.0` first. Stuck: `git fetch --force --tags origin`, then
  `scripts/beta/auto-release.sh retry v0.21.2`.
- [ ] **Spot checks.** Press Help: one big "Using RouteMaker" button, then the version and the map's
  credits; the button opens the Using page. On the beta, open the beta notice: two buttons, "Sign up
  to test here!" (the Android beta page) and "Using RouteMaker". The Stress ratings page shows four
  comparison charts under "How our ratings compare with each agency's".
- [ ] **Rollback.** The v0.21.1 front end. Nothing in the database, the api or the map changes.

## Deploying v0.21.1

A patch: a ride started away from its start (more than 200 m, about 650 ft, and off the line) asks
"Go to the start" (the start its stop 1, then on along the planned route unchanged) or "Join from
here" (re-planned onto the route ahead). Riding to the start, the planned route takes over
anywhere within 200 m of it, so any entrance of a big place counts (#994 and its follow-up).
**Front end only** (`frontend/`), with the version in `pyproject.toml`, `src/routemaker/__init__.py`
and `README.md`. **No migration, no `src/` code change, no `src/pipeline/`, `lua/`, compose,
Caddyfile, nginx, Dockerfile or requirements change, no new environment variable, outbound host or
scheduled job, no `mobile/` change and no map rebuild.**

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.21.1 (annotated) on
  that commit, from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": fast-forward the checkout, then
  the front end. The api image need not be rebuilt (only its version string changes); rebuild it
  with `docker compose build api` and recreate `api worker` if the version shown should say 0.21.1.
- [ ] **Beta**, by its agent, once its deployed tag (`$RM_STATE/cd/deployed-tag`) is v0.21.0: the
  gate sees `frontend/`, `pyproject.toml` and `src/routemaker/__init__.py` (docs and `.md` files are
  inert), and deploys. While v0.21.0 is
  not yet marked deployed, the diff from v0.20.0 still carries `src/pipeline/schema.py` and the agent
  stops on v0.21.1 too: finish the v0.21.0 hand ship and `mark-deployed v0.21.0` first (then
  `resume` if paused). Stuck: `git fetch --force --tags origin`, then
  `scripts/beta/auto-release.sh retry v0.21.1`.
- [ ] **Spot checks.** Plan a route whose start is a few blocks from where you stand, press Start
  ride: "Not near the start. Go to the start first, or join the route from here?" is said and shown.
  Go to the start: "Not near the start: going there first.", the line runs from you to the start,
  then the planned route; the start shows as stop 1, "Stop 1, Start.", and the plan's stops
  follow as 2, 3 and so on. Join from here instead: a new route from you onto the route ahead.
  Unanswered, riding on 200 m closes it by itself. Standing at the start, or on the route part way along, the ride starts
  as before (part way, "Already done?" asks about the stops behind).
- [ ] **Rollback.** The v0.21.0 front end. Nothing in the database, the api or the map changes.

## Deploying v0.21.0

Transit in a ride: the stops and time left on board, the line along its track and each stop's
time (#976, #978), resuming a trip after switching apps (#979); the 2026-11-05 repo review's fixes
(#980: Group and Mass Ride links keyed per plan with "Same ride or a new one?" after 12 hours or
after a change,
Detour's Go round, Reach's own rate limits and costing per ride type, the MCP connector's `reach`
and `compare_places` answered in process, closures checked as far as a plan reaches); the open data
download (#982); mile markers on the route line (#987); 671 Baltimore City owner rows corrected (#975); and a key of its own for the PC's
backup pull (#983).

**What changes for the host.** Migration 0056 (`shared_route_gone`, home's own table, never
shipped: `ship-data.sh` leaves it out). `src/pipeline/schema.py` and `writers.py` add the segment
column `stress_computed_half`, which the next map rebuild fills; the api reads it only where the
live table has it (`core.segment_info`), so the release runs on the current map. Reach has rate
limits of its own (`REACH`, `REACH_ISOCHRONES`, in code: no environment variable).
`scripts/build_transit_schedule.py` stores each rail pattern's track from `shapes.txt`; an old
schedule keeps working, drawn stop to stop. `scripts/beta/` (the agent, `alert.sh`'s PC-pull
watch, `receive-data.sh`, `ship-data.sh`) and `scripts/pc/` (the backup pull reads
`~/.config/routemaker/pull-beta-backups.env` and the pull-only alias of "A key that
can only pull backups"). **No `valhalla/*.json`, compose, Caddyfile, nginx, Dockerfile,
requirements, `lua/` or `mobile/` change, no tile `FORMAT_VERSION` change, no new environment
variable or scheduled job, and no new outbound host for the stack** (the open data export, run by hand on
the PC, reads Arlington's ArcGIS service; `--no-arlington` skips it). The routers need no restart. The beta agent's gate
stops on `src/pipeline/schema.py` (`reason=src/pipeline/schema.py: the live table layout
changed`), as at v0.19.0, though the column is optional: the beta ships by hand, with no map data
(the transit schedule only). At home, in order, with `</dev/null` on every docker command:

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.21.0 (annotated) on
  that commit, from the PC.
- [ ] **Rollback points and images**, as "Deploying a planner and front-end release", with the
  weekly rebuild paused or not due, and out of 07:00-07:30 UTC: tag the running api **and pipeline**
  images `pre-rel-<short>`, fast-forward the checkout, then `docker compose build api rebuild` (the
  pipeline image writes the new column at the next rebuild).
- [ ] **The api.** `docker compose run --rm --no-deps migrate` (0056), then
  `docker compose up -d --no-deps --no-build --force-recreate api worker`, and `rebuild` too once
  no rebuild job is queued or running. No router restart, no pre-draw.
- [ ] **The front end**, last.
- [ ] **The PC backup pull.** Its scheduled task runs the script from `~/src/RouteMaker`, not from
  the serving worktree, so fast-forward that checkout to the tag too, then run
  `install-backup-pull-task.ps1` again ("Off-box copies of beta backups", Install) so the task takes
  its v0.21.0 settings. `~/.config/routemaker/pull-beta-backups.env` and the pull-only key are in
  place (the owner set both up on 2026-11-06). Without the file each pull exits 1 saying so, and
  `alert.sh watch` reports it after 36 h. After the next 04:00 run, `pull-beta-backups.log` names
  the pull-only alias and says `marked=yes`.
- [ ] **The transit schedule**, rebuilt with the new script ("Transit schedule", Build it on the
  home PC), so rail lines follow their tracks. The build's report says "<system>: N of M patterns
  follow their track" for MARC, Light RailLink and the rest; a system with none is drawn straight
  from stop to stop ("Transit schedule"). The beta takes the new schedule in its hand ship below.
  Without this step the lines are drawn straight stop to stop until the next 45-day refresh.
- [ ] **The open data download**, after the api is on v0.21.0 (the command ships in it): "The open
  data download (after a map swap)", step 1 on the PC, then `agency-comparison.json` beside the docs
  generator and the stress page regenerated; the upload to a `data-<date>` GitHub release waits for
  the owner's go, and comes **before the beta deploy**, since the Acknowledgements page's "Download
  our data" link points at it.
- [ ] **The overrides: none until the owner confirms.**
  `fixtures/overrides/2026-11-04-owner-baltimore-city-review.json` (671 rows, corrected in #975) is
  loaded only after the owner confirms that file (stdin, dry run then `--confirm`), and before the
  map rebuild that should carry it.
- [ ] **Beta**, by hand as "Shipping an update later" (docs/BETA-RUNBOOK.md): pause the agent
  (`pause --wait`), snapshot the database (`--label release`), copy `index.html`, check out the
  tag, set `TAG=`, `check_beta_compose.py` ("beta compose: ok"), build the api image, migrate in the
  migrate container (0056), start api and worker, the front end, `smoke-test.sh --local --trails`
  then `--public`. No map data, no router restart, no pre-draw. The rebuilt transit schedule goes
  in this ship, while the agent is paused: the `transit` part alone (BETA-RUNBOOK, "the bundle carries
  the transit ride types' schedule"). The agent changed:
  `mark-deployed v0.21.0`, then `scripts/beta/auto-release.sh install`, then `resume`.
- [ ] **Spot checks.** A bike + transit ride on MARC or Metro: on board, the card shows the stops
  and minutes left and an arrival time, the stop list shows each stop's time, and the ride map
  draws the line in its colour along the track, with the stop to get off filled. Where am I? on the
  train gives the line and the stop to get off, never "arrived". Switch apps on the train, come
  back, press Resume: the trip carries on. In a ride, Detour's menu offers "Go round: road closed
  ahead". Copy a Group Ride link, change the plan and copy again: "Same ride or a new one?"; Same ride
  gives the first link, New ride a new one. Plan > Find > Reach
  on Walk draws rings. Acknowledgements shows "Download our data". A route over 5 miles, zoomed in
  to street level (zoom 11+), shows a white dot each mile and a larger numbered dot at 5; with Units
  in kilometers, a dot each km (zoom 12+) and a 5 at 5 km.
- [ ] **Rollback.** The `pre-rel` api and pipeline images (`--force-recreate api worker rebuild`)
  and the v0.20.0 front end. Migration 0056 only adds a table: the v0.20.0 api ignores it, so the
  database stays migrated. A schedule rebuilt with tracks still works with the v0.20.0 api (it
  ignores `shape` and `cuts`). On the beta: rollback C (docs/BETA-RUNBOOK.md; the snapshot is there if needed), then
  `auto-release.sh hold v0.21.0` so the agent does not deploy it again.

## Deploying v0.20.0

Reach's rings (#961, #962), Ride's stress ribbon (#956, #960), long-trail names and quieter route
numbers (#951, tile `FORMAT_VERSION` 15 to 16), Baltimore City DOT's racks (#953), 698 Baltimore City
owner rows (#955), the dark tunnel page (#957), the follow crosswalk fix (#959), Ride the rest waiting
for a fix (#950) and the 2026-11-04 repo review's fixes (#963, #964, #967, #969). **No migration, no
`src/pipeline/` change, no `lua/` change and no map rebuild.** What does change for the host: every
`valhalla/*.json` (the `isochrone` action and `max_exclude_polygons_vertices` 1000), the Caddy image
(2.8 to 2.10) and the Caddyfile, `docker/api.Dockerfile` (the amenity files Reach counts),
`scripts/beta/` (the agent prunes `_before_` databases over 6.5 days old), `scripts/pc/` (the backup
pull) and `mobile/` (the links manifest). The tile format change means **both** images are built
(the `rebuild` service pre-draws tiles too, and a format-15 rebuild image would evict the api's
format-16 cache every week). The beta agent's gate stops on the compose image line and the
Dockerfile, so the beta ships by hand. At home, in order, with `</dev/null` on every docker command:

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.20.0 (annotated) on
  that commit, from the PC.
- [ ] **Rollback points and images**, as "Deploying a planner and front-end release", with the
  weekly rebuild paused or not due, and out of 07:00-07:30 UTC: tag the running api **and pipeline**
  images `pre-rel-<short>`, fast-forward the checkout, then `docker compose build api rebuild`.
- [ ] **Caddy**, after the fast-forward: `docker compose pull caddy`, validate the new Caddyfile against the new image ("Changing
  the Caddyfile on a running stack" in docs/DEPLOYMENT.md), then
  `docker compose up -d --no-deps --no-build --force-recreate caddy`.
- [ ] **The routers, before the api.** Restart every router that runs, the `offroad` profile's
  included ("A release that changes `valhalla/*.json`" in docs/DEPLOYMENT.md). The v0.19.1 api works with the new configs; the new api
  needs them (Reach answers nothing and a ride past several curved closures can read as no route).
- [ ] **The api.** `docker compose up -d --no-deps --no-build --force-recreate api worker`, and
  `rebuild` too once no rebuild job is queued or running. No `migrate`. Then the tile pre-draw
  (the `FORMAT_VERSION` change).
- [ ] **The front end**, last.
- [ ] **The overrides: none in v0.20.0.** `fixtures/overrides/2026-11-04-owner-baltimore-city-review.json`
  is not loaded with this release: the release review found rows whose evidence is another street's
  block, so the file is being corrected first. Load it (stdin, dry run then `--confirm`, as in "First
  rebuild on a fresh host") only after the owner confirms the corrected file.
- [ ] **The PC backup pull**, once: "Off-box copies of beta backups", Install.
- [ ] **Android**, a new build (the links manifest changed).
- [ ] **Beta**, by hand as "Shipping an update later" (docs/BETA-RUNBOOK.md): no data bundle; build
  the api image, restart the routers (all of them that run, `valhalla-paved` included: its config
  changed too), the api and worker, the pre-draw, the front end, `smoke-test.sh --local --trails`
  then `--public`. Caddy is not used on the beta. The agent changed: `mark-deployed v0.20.0`, then
  `scripts/beta/auto-release.sh install`, then `resume`. Its first pass drops any `_before_`
  database over 6.5 days old (the owner chose this, 2026-11-04). The beta's map swap from the
  v0.19.0 rebuild is separate and still waits for the owner.
- [ ] **Spot checks.** Plan > Find > Reach draws rings from a point and the 15/30/45/60 choice changes
  them. In a ride, More > Stress shows the colour ribbon under the turns. A long trail's name shows
  along it at a mid zoom, and US route shields are grey in dark mode. Baltimore racks show with the
  Water and restrooms layer from zoom 17. A route past several closures still plans.
- [ ] **Rollback.** The `pre-rel` api and pipeline images (`--force-recreate api worker rebuild`),
  the v0.19.1 front end, and Caddy back on the 2.8 digest (check out v0.19.1's `compose.yaml` and
  `Caddyfile`, then recreate `caddy`), then the pre-draw again (format 15). The routers need no
  restart back: a v0.19.1 api sends fewer vertices and no isochrone call. Loaded override rows stay;
  retire them with the loader if they must go.

## Deploying v0.19.1

A patch: Ride's settings as a popup (#932, #934, #936) and bike + transit rides that go on at the
station (#937), plus the transit boarding screen and the "MARC MARC" wording fix (#941, which
changes `src/core/transit.py`, so the api image is rebuilt). **No migration, no `src/pipeline/`
change, no `lua/`, compose, Caddyfile, nginx, Dockerfile or
requirements change, no new environment variable, outbound host or scheduled job, no `mobile/`
change and no map rebuild.** The beta agent deploys it by itself from the annotated tag.

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.19.1 (annotated) on
  that commit, from the PC.
- [ ] **At home**, as "Deploying a planner and front-end release": tag the running api image for a
  rollback, fast-forward the checkout, `docker compose build api`, `up -d --no-deps --no-build
  --force-recreate api worker`, then the front end. No `migrate`. Leave the v0.19.0 map rebuild and
  its swap alone: v0.19.1 runs on either map.
- [ ] **Beta**, by its agent, once its deployed tag (`$RM_STATE/cd/deployed-tag`) is v0.19.0: the
  gate sees `frontend/`, `scripts/`, `src/core/`, `src/routemaker/`, `tests/` and the version in
  `pyproject.toml` only, and deploys. While v0.19.0 is
  held or not yet marked deployed, the diff from v0.18.0 still carries `src/pipeline/schema.py` and
  the agent stops on v0.19.1 too: finish the v0.19.0 hand ship and `mark-deployed v0.19.0` first
  (then `resume` if paused), or ship v0.19.1 by hand as "Shipping an update later", then
  `mark-deployed v0.19.1`. Stuck: `git fetch --force --tags
  origin`, then `scripts/beta/auto-release.sh retry v0.19.1`.
- [ ] **Spot checks.** In a ride, the settings button opens a popup over the map with Colors, High
  contrast and Units first; switching Units changes the distances at once. A bike + transit ride
  shows no Done at the station and picks up the ride after the train. Bikeshare + transit's walking
  option starts a ride. A MARC boarding never says "the MARC MARC", and the boarding card shows a line badge
  for each line that makes the ride, with where it is signed to, then Get off, Next train (Next bus
  for a bus) and After that as rows.
- [ ] **Rollback.** The v0.19.0 api image and front end together. Nothing in the database or the
  map changes.

## Deploying v0.19.0

Metric mode (a Units setting), Ride's graphs of the next 2 miles, spoken trail turns and road
crossings, trail end markers and one-way trail profiles, stops on Walk and the transit ride types,
the Run loop length fix, "path beside" and "sidewalk beside" names, the faint-road rule, 175 Arlington owner rows (the
Bike Comfort Index review) and the v0.18.0 rebuild follow-ups (the closure probes read each build's
own list; the beta agent leaves a stopped `valhalla-paved` stopped when memory is short). **No
migration, no `lua/`, compose, Caddyfile, nginx, Dockerfile or requirements change, no new
environment variable, outbound host or scheduled job, and no `mobile/` change.** `src/pipeline/`
changed (the faint-road and "path beside" facts are written by the rebuild; `schema.py`'s change is a
comment only, no table changes, but the gate stops on any change there), and the Arlington rows are
owner overrides, so the map is rebuilt at the tagged commit and the beta agent stops on the tag
(`reason=src/pipeline/schema.py: the live table layout changed`):
the beta ships by hand with the data bundle. The release agent itself changed. At home, in order,
with `</dev/null` on every docker command:

- [ ] **The tag.** Once `test` and `a11y` are green on `main`, the owner tags v0.19.0 (annotated) on
  that commit, from the PC.
- [ ] **Images and the api.** Before the weekly rebuild or with it paused, and out of 07:00-07:30
  UTC: tag the running api and
  pipeline images for a rollback, fast-forward the checkout, `docker compose build api rebuild`,
  then, once no rebuild job is queued or running,
  `docker compose up -d --no-deps --no-build --force-recreate api worker rebuild`. No `migrate`.
- [ ] **The overrides**, only after the owner confirms each file, before the build so the map
  carries them: `load_access_overrides` as a dry run first, then with `--confirm`.
  `fixtures/overrides/2026-11-03-owner-arlington-bci-review.json`: 175 rows and 7 retired earlier
  owner rows. `fixtures/overrides/2026-11-01-owner-md-rating-review.json`: one more retire
  (way 987375476). Skip a file the PC already holds (the dry run says nothing changes).
- [ ] **The map**, at the tagged commit, in its own thread: the cloud box (`--beta-bundle` for the
  beta) or `run_rebuild_now`. Seven graphs, as v0.18.0. Before the swap, the stress-change report
  should show the Arlington rows' streets moving tier on top of the usual week's OSM changes; the
  faint-road and "path beside" changes move no tier. Then swap and restart the routers (as v0.18.0).
- [ ] **The front end**, last.
- [ ] **Beta**, "A new release sha" with the data bundle (docs/BETA-RUNBOOK.md), as v0.18.0 without
  the migrate, Caddy or nginx steps: the memory check first (`valhalla-paved` stays stopped under
  8803 MiB), pause the agent, snapshot, check out the tag, set `TAG=`, `check_beta_compose.py`
  ("beta compose: ok"), build the api image, `receive-data.sh verify`, `db --update-data
  --stage-only`, `sudo ... files`, `sudo ... db --update-data` (not during the 07:00 UTC backup),
  start api and worker, the
  pre-draw, the routers, the front end with the bundle, `smoke-test.sh --local --trails` then
  `--public`. The agent changed: `mark-deployed v0.19.0`, then `scripts/beta/auto-release.sh
  install`, then `resume`.
- [ ] **Spot checks.** Settings > Display > Units set to "Kilometers and meters" shows km first in Go and Ride. A
  ride's More menu offers the Stress and Elevation graphs. A trail shows compass end markers (N, S, NW and so on). A Walk
  with a stop plans. A Run from a start alone with a 5 km target comes back near 5 km. Kemp Mill Rd's
  bike-signed sidewalk reads "sidewalk beside Kemp Mill Road". A one-way trail's panel says "One way"
  and its profile runs the riding direction. A ride with Metric on says "Cross <road>" at a crossing and
  speaks metres, with no feet or miles. In Ride, the arrow moves up when the bottom panel grows. 15th Street NW is drawn faint beside its cycle track; Connecticut
  Avenue NW from Davenport to Everett is drawn as usual.
- [ ] **Rollback.** At home: the `pre-rel` images, `rollback_rebuild` and the v0.18.0 front end
  together (a v0.18.0 api refuses a settings save that carries `units`). Loaded override rows stay
  loaded; retire them with the loader if they must go. On the beta: the map
  tables by rename (rollback B, from `live_old`) with rollback A.

## Deploying v0.18.0

Road Bike (a ride type on its own graph, replacing the Avoid gravel box; junction waits weigh 3x),
Walk and Walk + transit, Avoid stairs, walk pricing, walks turn by turn and transit stop by stop,
transit trips re-checked while ridden, the Run ride type, the connector's new tools (and its My routes read), the
routing speed-up and the beta's staging swap. Two migrations (0054 adds `connector_grant.reads_routes`; 0055 gives it a database default, so the v0.17.0 api still creates grants after `migrate` and after an image rollback).
A seventh graph, `tiles/paved`, and its router `valhalla-paved` (profile `offroad`; 768M at home,
320M on the beta). **`lua/` changed, a Valhalla config was added, compose and the nginx template
changed, so the beta agent stops on the tag and the deploy is by hand**, with the map built at the
tagged commit. The Caddyfile changed (`/road-bike`, `/walk`, `/walk-transit`, `/run`). No Dockerfile or requirements change, no new
environment variable to set (`VALHALLA_PAVED_URL` has its default), no new outbound host (the trip
checks read WMATA through the existing shared cache) and no new scheduled job. No `mobile/` change,
so no Play build. At home, in order, with `</dev/null` on every docker command:

- [ ] **The build's commit.** The cloud box builds home's checkout HEAD, and `import-result.sh` and
  the beta's `receive-data.sh verify` refuse a build from another commit unless given
  `--allow-sha-mismatch`. A map built from the release branch before its last planner or front-end
  PRs (no change under `lua/`, `valhalla/`, `src/pipeline/` or `scripts/cloud/` since the build)
  is the same map: install it with `--allow-sha-mismatch` and say so in the run's notes.
  Once `test` and `a11y` are green on `main`, the owner tags v0.18.0 (annotated) on that commit. The
  agent stops and alerts: expected.
- [ ] **Images, migrate, the api.** Before the weekly rebuild (Tuesday 08:00 UTC) or with it paused,
  and out of 07:00-07:30 UTC: tag the running api and pipeline images for a rollback, fast-forward
  the checkout (`lua/` is mounted from it; the new tags are written only on the paved graph, so a
  rebuild between here and the next step changes nothing else), `docker compose build api rebuild`,
  then `docker compose run --rm --no-deps migrate` (0054 adds `reads_routes`, default off: a grant
  given before cannot read My routes until the rider connects again; 0055 keeps that default in
  the database). Then, once no rebuild job is
  queued or running, `docker compose up -d --no-deps --no-build --force-recreate api worker rebuild`.
- [ ] **Caddy.** The Caddyfile adds `/road-bike`, `/walk`, `/walk-transit` and `/run`: validate it in a throwaway container and recreate
  caddy alone ("Applying a Caddyfile change"). This also brings `/about/android-beta.html`, in
  `@frontend` since v0.16.3, to this host, whose caddy was not recreated after v0.16.2/v0.16.3. Check:
  `curl -sI https://<site>/road-bike` is a 302 to `/#preset=road-bike`, and
  `curl -sI https://<site>/about/android-beta.html` is a 200 once the front end is published.
- [ ] **The data directory.** `sudo sh scripts/prepare_data_root.sh --env-file ./.env` (it adds `tiles/paved` and
  `tiles/paved/current`, owned 10001). Never name `valhalla-paved` in an `up` before its first
  build: Docker would make `tiles/paved` as root, which the rebuild cannot write.
- [ ] **The map**, at the tagged commit: on the cloud box (`send-inputs.sh` from this checkout, or
  `launch.sh`, with `--beta-bundle` for the beta), or `run_rebuild_now` here. Seven graphs: about
  20-25 minutes and one extract more than v0.17.0, about 1.1 GB more per kept build (2.2 GB with
  `previous`), and the cloud result's `tiles-paved.tar` (a result without it is refused). The
  rebuild's memory peak is unchanged (one graph at a time). Before the swap, the stress-change
  report and Review's lists show no tier moved by this release (the new tags are on the paved graph
  only). Then swap.
- [ ] **The routers.** Restart the four. Where the `offroad` profile runs, start the new one once:
  `docker compose --profile offroad up -d --no-deps --no-build valhalla-paved`; until it has a
  container, a `restart` that names it restarts none of the three. Then
  `docker compose --profile offroad restart valhalla-offroad valhalla-mtb valhalla-paved` and
  `sync_upstreams`. On the PC the profile is off: Road Bike is then planned on the standard graph,
  where gravel is packed gravel, and the answer warns of packed gravel (#898). Starting `valhalla-paved` alone
  there needs about 0.75 GB spare; the owner, 2026-11-02: "pc can have road bike too", so start it there alone (`docker compose --profile offroad up -d --no-deps --no-build valhalla-paved`) after checking memory inside WSL.
- [ ] **The front end**, last.
- [ ] **Beta**, "A new release sha" with the data bundle (docs/BETA-RUNBOOK.md):
  - Before anything, the memory check: `free -m` "available" plus the resident memory of this
    project's running containers (`docker stats --no-stream`) at least 8803 MiB (the 8086 MiB
    startup peak with `valhalla-paved` plus 0.7 GiB). Under it, ship as below but leave
    `valhalla-paved` stopped; the agent does the same check and leaves it stopped with a warning.
    `df -h /data`: room for the bundle, a second copy of each graph, and about three times the live
    tables for the staging.
  - Pause the agent (`pause --wait`, then `status`); stop api and worker, snapshot the database
    (`--label release`), copy `index.html`.
  - Check out the tag, set `TAG=`, `"${RM_PY:-python3}" scripts/check_beta_compose.py --env-file .env` ("beta compose: ok",
    7.65 GiB resident); build the api image; migrate in the migrate container (0054, 0055).
  - Data: `receive-data.sh verify`, then `db --update-data --stage-only` (the staging swap's first
    run: `live_next`, row counts checked), `sudo ... files` (installs `tiles/paved`), then
    `sudo ... db --update-data` (the rename; `live_old` keeps v0.17.0's map tables). Not during the
    07:00 UTC backup. Check: `\dn` shows `live` and `live_old` and no `live_next`, and there is no
    `routemaker_stage` database.
  - Start api and worker; the stress-tile pre-draw.
  - Restart the four routers one at a time; then
    `scripts/beta/beta-compose.sh up -d --force-recreate valhalla-offroad valhalla-mtb valhalla-paved`
    (leave out `valhalla-paved` if memory was short); `sync_upstreams`.
  - Re-render and install the nginx site (step 9: the `road-bike`, `walk`, `walk-transit` and `run` preset links), `nginx -t`, reload.
  - The front end comes with the bundle (`files`), `index.html` last.
  - `smoke-test.sh --local --trails` (now checks `road-bike` on the `paved` graph), then `--public`.
  - The agent and router hook changed: `scripts/beta/auto-release.sh install` and, where installed,
    `scripts/beta/restart-routers.sh install`, from the new checkout. `mark-deployed v0.18.0`
    comes first (`install` refuses until the running tag is marked), then the two installs, then
    `resume`.
- [ ] **Spot checks.** A Road Bike route answers `"variant": "paved"`. A Mall gravel walk is ridden
  on Default and avoided on Road Bike. A link with `avoidgravel=1` opens as Road Bike. `/road-bike`
  opens Road Bike on both hosts. Walk and Walk + transit plan, and Start walk follows the turns; a Run from a start alone with a target distance plans a loop near that length. A
  Bike + transit ride re-plans once every 2 minutes until boarding. The connector's consent page
  lists "read your saved routes".
- [ ] **Rollback.** At home: the `pre-rel` images; the database stays migrated (0055's default lets the
  old api create grants). After the first v0.18.0 rebuild, `rollback_rebuild` withdraws
  `paved` (its first build) and stops `valhalla-paved`. On the beta: the map tables by rename
  (rollback B "by rename", from `live_old`) with rollback A. Before rolling the code back to v0.17.0
  (rollback C), `scripts/beta/beta-compose.sh stop valhalla-paved`: v0.17.0's compose has no such
  service and its 7.35 GiB budget does not count it.

## Deploying v0.17.0

Bike racks, the sunrise-and-sunset theme, battery savings, Potential closures with planned work,
Maryland's Road Closure Reporter, the region-wide rating review (four override files), packed
gravel, the one-way rule (#864) and the follow and snap crosswalk fixes. No migration, no compose,
Caddy, nginx or Dockerfile change and no new environment variable. **`lua/routemaker_remap.lua`
changed (#877), so the beta agent stops on the tag and the deploy is by hand**, with the map built
at the tagged code (the 2026-11-01 spot build from release/v0.17.0 c6b9b543 carries every graph
change: #864, #868, #877, #878). At home, in order, with `</dev/null` on every docker command:

- [ ] **Outbound hosts.** Add `geo.dcwater.com`, `gisportal.wsscwater.com` and `mdgeodata.md.gov`
  (443) to beta's egress list, and home's if it is filtered (the worker's hosts in
  docs/BETA-RUNBOOK.md, "3. Make `.env`"). Planned work only logs an outage, but `sha` is routed round: with no good read
  in 45 minutes it fails every `refresh_dc_closures` run (src/core/closure_sources.py).
- [ ] **Tag and images.** Once `test` and `a11y` are green on `main`, the owner tags v0.17.0
  (annotated). The agent stops and alerts on the `lua/` change: expected. Then, before the weekly
  rebuild (Tuesday 08:00 UTC) or with it paused: tag the running api and pipeline images for a
  rollback, fast-forward the checkout (`lua/` is mounted from it, so the gravel rule applies from
  here), `docker compose build api rebuild`, and once no rebuild job is queued or running
  `docker compose up -d --no-deps --no-build api worker rebuild`. The tag also starts a Play
  internal-testing build (mobile/README.md changed); it can be ignored.
- [ ] **The four review files, each only after the owner confirms that file:**
  `2026-11-01-owner-{dc,md,va,wv}-rating-review.json` (19,802, 34,781, 8,998 and 434 ways).
  Dry run first, then `--confirm` ("A deploy that changes the crossings fixture or loads access
  overrides", step 3). They were loaded on the PC on 2026-11-01; the release then corrected
  twelve public notes ("but Riding" to "but riding", nine DC, three MD), so the DC and MD dry
  runs show only those notes changed and VA and WV show nothing.
- [ ] **The map.** Swap in the spot build (or rebuild at the tag). Before the swap, the
  stress-change report and Review's lists (service roads and alleys move from LTS 1 to 1.5; about
  181 DC one-ways, 13.8 mi, close their other direction), and a Mall gravel walk routes on
  Default. Then swap and restart the routers.
- [ ] **Beta**, "A new release sha" with the data bundle: pause the agent; stop api and worker,
  snapshot the database, copy `index.html`; check out the tag, set `TAG=`,
  `check_beta_compose.py`; build the api image; `receive-data.sh verify`, `files`,
  `db --update-data`; start api and worker; the stress-tile pre-draw; restart the four routers,
  recreate `valhalla-offroad` and `valhalla-mtb`, `sync_upstreams`; the front end last; the smoke
  test (`--local --trails`, then `--public`); `mark-deployed v0.17.0`; resume the agent.
- [ ] **After the first closures runs:** the log's `closures:` line has `sha N closures` and the
  planned-work counts, with no "no good read in time"; Plan's Potential closures layer shows
  markers; a Maryland closure is routed round. Spot checks: a DC alley's road panel reads LTS 1.5;
  a reviewed road's Why line is its public note; Share live posts once a pace and a watcher reads
  every 15 s.

## Deploying v0.16.0

The ratings recalibration: owner rules for MDOT SHA and DDOT's levels, the same rating rules in
every state (West Virginia's speed law), busy-street half steps, counts on both carriageways of
divided roads, and three owner override files. No migration, no `lua/` change, no new download.
The tag deploys the code on beta's old data (new colours, old ratings); the ratings arrive with
the data. At home, in order, with `</dev/null` on every docker command:

- [ ] **Tag and images.** Once `test` and `a11y` are green on `main`, the owner tags v0.16.0
  (annotated). Then, before the weekly rebuild (Tuesday 08:00 UTC) or with it paused: tag the
  running images for a rollback, `docker compose build api rebuild`, and once no rebuild job
  is queued or running `docker compose up -d --no-deps --no-build api worker rebuild`. Then
  the front end. The tag also starts a Play internal-testing build, though the app did not
  change; it can be ignored.
- [ ] **Urban areas first.** Remake `urban-areas.json` with `--extract` and `--urban-areas`
  only ("First rebuild on a fresh host", the command under "Remake `urban-areas.json`"),
  never with the `--volume` pairs, which would drop Maryland's counts. The `urban ways`
  count it prints should rise from the 2026-09-25 list. Without it the rebuild stops: the
  list has no West Virginia way.
- [ ] **`agency-lts.json` again, on the PC.** The MDOT SHA rules exist only as the `read_as`
  fields the v0.16.0 installer writes; an older file loads without a word and ships SHA's
  published levels. Reinstall `moco ddot mdot-sha` with `--mdot-aadt` and `--urban-areas`
  ("Agency stress ratings (agency-lts.json)"), read its `read by the owner's rule` lines, then
  copy it into `$DATA_ROOT/reference/` (sudo cp, chown 10001:10001, chmod 644).
- [ ] **The three override files, one at a time, each only after the owner confirms that
  file:** `2026-10-30-owner-q-r-first-streets-nw.json`, `2026-10-30-owner-wv-county-roads.json`
  (after the urban list), `2026-10-31-owner-virginia-ratings.json`. Dry run first, then
  `--confirm` ("A deploy that changes the crossings fixture or loads access overrides", step 3).
  No way in them is in an earlier file, so each dry run shows only creates.
- [ ] **Rebuild** (`run_rebuild_now`, or `send-inputs.sh` for the cloud box). In the log:
  `counts shared with N opposite carriageways (ddot, mdot-sha, vdot)`, the agency-ratings
  `changed tier` lines, and West Virginia in the `state polygons from <pbf>: DC, MD, VA, WV` line.
- [ ] **Before the swap**, the stress-change report (whole levels only; expect large West
  Virginia moves from the urban list, and DC second carriageways moving from the 2020 Roadway
  Block count to DDOT's 2024 count) and Review's changed-roads lists, which show the half
  steps the report does not. Then swap, restart the routers, and check a road panel: an SHA
  road and a DDOT-rated DC block each show a "read as" line.
- [ ] **Beta's data:** pause the agent, `ship-data.sh`, then `receive-data.sh verify`, `files`
  and `db --update-data`, the pre-draw, the router restarts and `sync_upstreams`, the smoke
  test, and resume the agent. Build the data at the tagged commit: `receive-data.sh` checks the
  bundle's commit.

## Deploying v0.9.0

Two migrations (`0034_review_dc_no_bike_queue`, `0035_assistant_key`), both plain schema changes
that reverse cleanly; no new tile format and no rebuild. Deploy it as "Deploying a planner and
front-end release" (below). No new settings: live Metrobus and train positions reuse
`WMATA_API_KEY` and `api.wmata.com`.

- **Needs a rebuild to take effect:** bike-signed parking aisles and driveways open to through
  routes (`lua/routemaker_remap.lua`), the DC circle parks and NPS land in the CBD, and the
  Review queue of suspected no-bike paths (it reads "not wired" until a rebuild writes its report).
  On the current map nothing changes and nothing breaks.
- **Needs a new phone app build:** Send to Garmin, a link shared to the app, and the new icon.
- **Beta alerts** (`scripts/beta/alert.sh`) post from the server's login user, not a container:
  `discord.com:443` must be allowed for the host itself. Install them and re-run
  `auto-release.sh install` as BETA-RUNBOOK.md's "Alerts" says, so the agent's installed copy
  can post too.
- **AI assistant key** (retired in v0.12.2: assistants connect through the site's connector; `assistant_key` table, `core.models.AssistantKey`): one per account, only
  its SHA-256 kept. An assistant's MCP server (mcp/README.md) sends it in `X-RouteMaker-Key` to
  `POST /api/keyed/routes`, which only adds a route to that account's My routes, under the
  address limit, then the account's write limit. The rider removes it in Settings > Account;
  deleting or banning the account deletes it. Behind the
  beta's password gate the MCP server (not the site) needs `ROUTEMAKER_BASIC_AUTH` as well: the key travels in its
  own header.

## Deploying v0.8.2

No migration, no new tile format and no rebuild: closures beside the detour and the Road
closed button, the streamlined Plan panel, bikeshare docks in every ride type, places to see
from the widest zoom, and following an opened GPX track exactly. Deploy it as "Deploying a
planner and front-end release" (below), `docker compose build api` then `up -d --no-deps
--no-build api worker` and the front end, after v0.8.1 is deployed. `send-inputs.sh` now
refuses a reference folder without `scenic.json` ("The Scenic layer (v0.8.0)", steps 1 and 2).
The beta takes it through its CD agent.

## Deploying v0.8.1

Two migrations (`0032_review_stretches`, `0033_review_item_ways_db_default`), stress-tile
format 10 (every street from zoom 12), rural expressways at LTS 4.5 rather than Avoid, and a
rebuild that refuses to run without `agency-lts.json`. At home, in order, with `</dev/null` on every docker command:

- [ ] **Images, one TAG.** Tag the running images for a rollback, then
  `docker compose build api rebuild`, never `build api` alone, so the weekly rebuild's
  pre-draw draws format 10 too ("Deploying a change to what the tiles draw", steps 0
  and 1; rollback points in "Deploying a planner and front-end release", below).
- [ ] **Migrate, then the api.** `docker compose run --rm --no-deps migrate` (0032 adds
  `stretch` and `ways` to `review_item` and `stretch` to `review_ruling`; 0033 gives `ways` a
  database default, so a v0.8.0 worker still writes Review's rows through the deploy and
  after an image rollback; nothing to migrate back), then `docker compose up -d --no-deps
  --no-build api worker`; once no rebuild job is queued or running, `docker compose up -d
  --no-deps --no-build rebuild` too.
- [ ] **Pre-draw at once:** `docker compose exec -T api python manage.py
  predraw_stress_tiles` ("Deploying every street from z12 (FORMAT_VERSION 10)"; only
  `-v10"` stress tags after it). Then the front end.
- [ ] **Review's lists, with the routers up:** `docker compose exec -T api python manage.py
  compute_review_queue`. A stretch is named by the router; with it down the log says "the
  router was silent" and the table's names are kept, so run it again once the routers
  answer ("Review mode: shipping and its lists", step 2).
- [ ] **Reference files, before the next rebuild or cloud send:** `agency-lts.json` for
  `moco ddot mdot-sha`, in one run on the PC ("Agency stress ratings (agency-lts.json)";
  read its `ddot: level read from <field>` line); without it the rebuild and
  `send-inputs.sh` refuse. And `counties.geojson` (`install_reference_data.py --counties`)
  for Review's Area column and the stress change report.
- [ ] **Required since v0.16.0, urban areas:** remake `urban-areas.json` from the current extract
  (the 2026-09-25 list has no West Virginia way, and the rebuild now stops on that)
  (`install_reference_data.py` with `--extract` and `--urban-areas` only, never the
  `--volume` pairs; "Deploying v0.16.0"). A way newer than the list reads as rural, and a rural expressway posted 50 mph or
  more is now LTS 4.5, so a newly split urban expressway would come out LTS 4.5, not Avoid.
- [ ] **The rebuild** (or "Rebuilding on the cloud box"): the extract is remade once, for the
  new clip ("The source extract"). Read the `agency stress ratings` lines (no
  `warning: no segment carries`), and work "Rebuild checklist: Harford Road (decision 282a)".
- [ ] **After the swap:** Spesutie Island Road at Aberdeen Proving Ground is closed
  (military), not rated; Wickham Road (way 62828504) is 25 mph; the road panel on a rural
  expressway says "Rural highway-like road, posted 55 mph: high stress, but often no way
  around" at LTS 4.5; Review's lists are filled (a cloud
  build's dry run does it).

The beta takes it through its CD agent (docs/BETA-RUNBOOK.md: the migration and the format-10
pre-draw are its own steps); Review is home's only.
