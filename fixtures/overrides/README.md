# Access overrides decided outside the admin

Approved `Override` rows are the plan's one audited path for correcting OSM's
access tags (`pipeline.overrides.load_approved` reads nothing else, and the
rebuild's `APPLY_OVERRIDES` stage applies them). Most rows are entered in the
admin. A correction the owner decides in conversation is checked in here
instead, as a versioned file, so its wording and date are reviewed with the
change and survive in the row's `reason` and `evidence`.

A file is `{"version": 1, "decided": <date>, "decided_by": <who>, "rows":
[...]}`, each row `{"kind": "access", "osm_way_id": ..., "value": {tag: value},
"reason": ..., "evidence": ...}`. `decided` and `decided_by` are for the reader
and the reviewer; the loader reads only `version` and `rows`. `value` may write
only the keys an access override may (`pipeline.overrides.ACCESS_KEYS`).

`manage.py load_access_overrides` loads one. It is dry unless `--confirm` is
passed, attributes the rows to the instance admin named by `--actor` (a Discord
user id; any other account is refused and the refusal audited), and writes what
the admin path writes: the row, approved, and an audit entry for the add and
for the approval. It is idempotent - a row already approved with the same kind,
way and value is left alone - and refuses the whole file, before writing, on a
malformed row, a key outside `ACCESS_KEYS`, a way named twice, or an approved
row on the same way that disagrees.

`--actor` is named on the command line and is not authenticated: the command
checks that the id belongs to an active instance admin, and nothing checks that
the person at the shell is that admin. Every audit entry it writes says so in
its `detail`. On a fresh host the admin's account exists only after their first
Discord sign-in, so load overrides after that: step 7 of "First rebuild on a
fresh host" in docs/OPERATIONS.md is where a fresh host does it.

The api image carries `src/` and not `fixtures/`, so the file goes in on
standard input:

    docker compose exec -T api python manage.py load_access_overrides - \
        --actor <discord user id> < fixtures/overrides/<file>.json
    # read what it would do, then the same with --confirm

The rows take effect on the next rebuild, and only in the order below.

## Order: deploy, reinstall the crossings, load, rebuild

A row here can depend on a crossings row. The 2026-09-26 file opens Key
Bridge's Virginia approaches to every rider, and only the crossings fixture's
`roadway_mass_ride_only` on Key Bridge keeps ordinary riders off its roadway.
The rebuild reads the *installed* crossings, `<DATA_ROOT>/reference/crossings.json`,
not the fixture in its image. Loaded against an older install, these rows route
standard and e-bike riders over the Key roadway. So:

1. Deploy the api and rebuild images from the merged branch.
2. Reinstall the crossings:
   `docker compose exec -T rebuild python3 scripts/install_reference_data.py --data-root /data`
3. Load the file, dry run first, then with `--confirm`.
4. Rebuild (`run_rebuild_now`), then restart the routers.

Do steps 1 to 3 before the next Tuesday 08:00 UTC rebuild, which runs on its
own. The new rebuild image refuses to run when the installed crossings differ
from its fixture, so a missed step 2 costs a refused rebuild rather than a bad
graph. The old image has no such check, so never load the rows while it is
still deployed. docs/OPERATIONS.md, "A deploy that changes the crossings fixture
or loads access overrides", has the whole procedure.

Two `--confirm` runs at the same moment can both create a file's rows. There is
no lock and no unique constraint. The duplicates are identical, so they apply
the same way; delete one of each pair.

## Undo

`approved` is read-only in the admin, so a loaded row cannot be un-approved.
Delete it in the admin (Overrides), either from the row's page or with the
delete action on a selection. Both are audited as `delete` with the admin who
did it. The graph changes on the next rebuild; the running routers keep what
they were built with until then. Rerunning the loader on the same file creates
a deleted row again, so a deliberate removal also removes the row from the file
in a reviewed commit.

| File | Decision |
|---|---|
| `2026-09-26-owner-bicycle-access.json` | Key Bridge's Virginia approaches and the 11th Street local span's south landing, including its run onto Martin Luther King Jr Avenue SE, are legal to ride (owner, 2026-09-26, in two answers; the file grew from six rows to twelve and reloading it adds only the new ones). See `fixtures/crossings/README.md`. Needs the crossings of 2026-09-26 installed first (above). |
| `2026-10-05-owner-dupont-underpass.json` | The Dupont Circle underpass of Connecticut Ave NW, N St to R St, and its portal ramps (OWNER-DECISIONS 416): ten ways, all OSM `bicycle=no`. "Bikes can pass underneath. There's no sign to say they are prohibited. Underneath is LTS4." A `bicycle=yes` access row and a tier-4 stress row each (hidden, category other). The surface roadway and service lanes around the circle are not in it (414). |

## Stress rows, and the files of 2026-09-27

A row may also be `"kind": "stress"`: the tier the rebuild gives the way after
classification (`pipeline.overrides.apply_stress`), and the adjustment that
tier makes. Tier 5 is "legal but avoid" (`routemaker.stress.Stress.AVOID`, the
owner's category of 2026-09-27). The same command loads them (`load_overrides`
is its other name); a way may carry one row of each kind.

A stress row's `value` (the owner, 2026-09-27: "something clickable as a link
to why we'd consider a particular stretch of road level 5, or also why a
particular stretch of road might be adjusted, perhaps hidden"):

```json
{
  "tier": 5,
  "adjustment_id": "pennsylvania-ave-se-dc-295-merge",
  "category": "sightlines",
  "visibility": "public",
  "annotation_status": "approved",
  "display": "route_only",
  "public_note": "Off-ramp traffic from DC 295 merges in at a blind corner."
}
```

- `tier`: 1 to 5. It may be below the classifier's tier: a down-adjustment
  ("we could down adjust a road if this is the better route among similar
  routes"). The direction, `up`, `down` or `same`, is not in the file; the
  rebuild takes it against the classifier's tier.
- `adjustment_id`: lower-case words joined by hyphens, at most 64 characters,
  stable across rebuilds, and shared by every way of one stretch. Rows sharing
  one must agree on everything but the way.
- `category`: `speed`, `road_conditions`, `driver_behaviour`,
  `intersection`, `sightlines`, `better_among_alternatives` or `other`.
- `visibility`: `public`, or `hidden` for an adjustment a rider sees only as
  "adjusted".
- `annotation_status`: `proposed` until the owner has approved the category
  and the note, then `approved`. A proposed one is carried like a hidden one.
- `display`: where a public note may be shown. `route_only` is the summary of
  a route that rides over the stretch and nowhere else (the owner, 2026-09-27:
  "In many cases there's an acceptable trail. Only provide the warnings if the
  route goes over the road."); `map` is that and a click on the map as well.
- `public_note` (optional): at most 200 characters for a rider to read. It
  describes the road and its traffic, never a neighbourhood or its people (the
  owner's rule); the loader refuses the words such a note would most likely
  use, and review is the real guard.

The row's `reason`, the owner's own words, is for the audit trail and is never
shown: it stays in the override row. The rebuild writes the adjustment to
`segment.stress_adjustment_id`, and only for a public, approved adjustment also
`stress_computed_tier`, `stress_adjustment_direction`,
`stress_adjustment_category`, `stress_adjustment_note` and
`stress_adjustment_display`. A route's answer lists the adjustments it rides
over (`stress_adjustments`, `core.routing.adjustments_used`). Reloading a file
whose adjustment fields changed on the same tier updates the approved row in
place (audited as a change); a different tier is a conflict to resolve in the
admin. A stress row typed into the admin as `{"tier": n}` still sets the tier,
as a hidden adjustment named `way-<id>`.

- `2026-09-27-owner-stress.json`: the owner's curated tiers - US 340's William
  L. Wilson Freeway, the Benning Road and Frederick Douglass bridge roadways,
  and Pennsylvania Avenue SE eastbound from the DC 295 off-ramp merge east of
  the Sousa Bridge to Fairlawn Avenue SE ("Looking at it, there's a highway
  offramp with a blind corner. It's a level 5 road afterwards.") and westbound
  through the DC 295 ramps to the bridge ("Yes, avoid westbound too",
  2026-09-28), at 5; the
  11th Street local span and its south landing (the owner's "Steer to the
  path", whose separate penalty was retired for this tier), and the Sousa
  Bridge roadway, at 4. The owner approved loading it on 2026-09-27 ("Yes, load
  it"); docs/OPERATIONS.md, "A deploy that changes the crossings fixture or
  loads access overrides", gives the order. Its categories and notes were
  proposed here and approved by the owner the same day for `route_only`
  display; US 340 is `speed`. The westbound Pennsylvania Avenue SE note was
  approved as written on 2026-09-28.

- `2026-09-29-owner-ny-ave-ne.json`: New York Avenue NE from the Florida
  Avenue NE junction to the District line at tier 5 ("I'd put all of NY Avenue
  NE that's north of florida avenue as AVOID."), 71 ways, 6.7 mi, both
  carriageways; hidden, category `speed`, no public note (no wording approved).
  The owner approved loading it before the rebuild of 2026-09-29.
- `2026-09-29-owner-montana-ave-ne.json`: Montana Avenue NE between Bladensburg Road NE and New York Avenue NE down to
  tier 3 ("However, montana avenue between bladensburg and NY ave is actually
  the better route to take"), its twelve LTS 4 ways; asked, the owner confirmed
  "Yes, set it to LTS 3 (Recommended)" and approved loading it before the
  rebuild of 2026-09-29.

- `2026-09-30-owner-veirs-mill-sidepath.json`: the Veirs Mill Road sidepath
  between the Rock Creek Trail and the Twinbrook Connector Trail, which OSM
  tags as a plain sidewalk, made `bicycle=designated` (ways 468762518 and
  791422825; "Local override (Recommended)", 2026-09-30) until the owner
  retags it upstream. `segregated=no` is not an access key and is left out.

An access file of the same day, `bicycle=no` on Pennsylvania Avenue SE east of
the bridge, was never loaded and is gone: the owner looked at the road and
chose tier 5 instead, so the road stays legal.

## Car-free corrections, and the file of 2026-09-28

An access row may write `motor_vehicle` (`"value": {"motor_vehicle": "no"}`)
for a road the owner knows is closed to motor traffic for good while OSM says
otherwise: the owner's "Our own correction (Recommended)" of 2026-09-28. The
facility class is taken after the row is applied, so the road is a path to
every ride type but Mass Ride, at every ride time; who may ride it does not
change.

- `2026-09-28-owner-beach-drive-nw.json`: Beach Drive NW in the District
  between Joyce Road and the Maryland line - nine ways, 2.53 km, that OSM tags
  open to cars on weekdays (six ways, 2.32 km, destination-only at weekends;
  three short ways at the Wise Road end, 212 m, closed at weekends). The owner:
  "(most of beach drive in DC is closed to car traffic permanantly)". The owner
  approved loading it on 2026-09-28 ("Yes, load it"), at the next deploy.
  Montgomery County's Beach Drive stays as OSM tags it, closed at weekends.

An access row may also write `access`, where the way's own `access` is what
blocks it. `access=private` makes upstream's transform mark a way private -
destination-only, for every mode - whatever its `bicycle` key says: it reads
the flag from `access`, `motor_vehicle` and `motorcar` alone. So opening such a
way to riders takes `access=permissive` beside `bicycle=yes`, and
`motor_vehicle=no` to keep it closed to cars (pinned in
`tests/lua/test_graph_entry.lua`).

- `2026-09-30-owner-capitol-drives.json`: Capitol Circle Drive and the
  Capitol Driveways, inside the Architect of the Capitol's polygon. The owner
  (OWNER-DECISIONS 130): "Yes, open them". 25 service drives mapped
  `access=private`, `bicycle=yes` (0.99 mi, 1.6 km) take `access=permissive`,
  `bicycle=yes`, `motor_vehicle=no`; four linear `highway=pedestrian` drives
  with no bicycle tag (0.16 mi, 263 m) take `bicycle=yes`: 1.15 mi in all, not
  the 1.9 mi first estimated. The thirteen pedestrian areas on the grounds,
  most of Capitol Driveway NE/SE as mapped, are not in it: upstream does not
  route an area, so no access row can open one.

- `2026-09-30-owner-arterials-east-of-anacostia.json`: 774 stress rows at
  tier 5 (Avoid), hidden, no public_note, category other, annotation
  approved, one adjustment per corridor. The owner (OWNER-DECISIONS 141): "I d
  put most of the Arterials east of the Anacostia river as avoid"; asked which
  to strike (144): struck "11th St SE", "Ridge Rd SE", "River bridges";
  everything else, South Capitol St SW included, approved to load as Avoid.
  The District's trunk, primary and secondary ways east of the river (812 in
  the draft, 57.4 mi) less 11th Street SE (7 ways), Ridge Road SE (13), the
  four ways that cross the river (Benning Road's and the Douglass Bridge's
  spans, both Whitney Young Memorial Bridge ways), and the nine ways the
  2026-09-27 file already curates: three of MLK Jr Ave SE at 4, a different
  tier, which the loader would refuse, and six of Pennsylvania Ave SE already
  at 5. Overpass bridges away from the river stay in. Load it after the
  2026-09-27 file. Five South Capitol Street rows (Martin Luther King Jr Ave SE
  to Mississippi Ave SE, ways 468820704, 590525532, 455234174, 468820714 and
  1528642818, about 0.34 mi (0.55 km)) were taken out on 2026-10-05 for
  OWNER-DECISIONS 432 ("Change south captiol street from MLK ave to Missisipi
  ave to LTS4. There's no other routes through there."): that stretch is LTS 4
  by the named corridor `fixtures/corridors/2026-10-05-owner-south-capitol-mlk-to-mississippi.json`,
  and the file lists them under `superseded`. An approved row outranks a
  corridor, so the five rows already loaded are deleted in the admin before the
  rebuild (docs/OPERATIONS.md, the rebuild bundle's step H); VALIDATE refuses a
  build where the stretch is not LTS 4.

## The agency-data files of 2026-10-01

Both written by `scripts/analysis/compare_agency_lts.py` (`moco`, `baltimore`,
with `--roadway`, so the tiers are the rebuild's with the agency street layers
conflated) from layers whose licence records are in `fixtures/datasets/README.md`.
They were proposals under `proposed/` until the owner approved loading them;
`tests/test_agency_overrides.py` holds them to the loader's validation and to
what the owner approved. Load them in the order above, after the 2026-09-30
files.

- `2026-10-01-owner-moco-lts5-avoid.json`: the Montgomery Planning layer's
  existing-condition LTS 5 as Avoid ("I think this version does not. They also
  have an LTS5, which we can mark as avoid.", OWNER-DECISIONS 149; "Load it
  (Recommended)", 181): 409 ways, 44.6 mi, tier 5, hidden, no public
  note, category other, annotation approved, in 44 adjustments (one per street;
  unnamed ways by the 0.01-degree cell, about 0.6 mi [1 km], their midpoint lies
  in). A way is in it where the LTS 5 record it lies along most covers at least
  half of it and our tier is below 5; motorways and ways another file curates
  are left out. **It needs the Montgomery County Planning credit**, which went in
  with it ("Roads to avoid in Montgomery County: Bicycle Level of Traffic Stress,
  Montgomery County Planning Department"; docs/OPERATIONS.md, "Licences, and the
  credits every map must carry"); a deployment that drops the rows drops the
  line with them.
- `2026-10-01-owner-baltimore-facilities.json` ("Load Baltimore facilities",
  OWNER-DECISIONS 182): 256 stress rows, the tier the classifier gives with the
  City of Baltimore's recorded bike lane, buffered, separated or contraflow lane
  tagged, where OSM has none and the tier would fall (hidden, approved), and
  180 `bicycle=designated` access rows on the footways and paths the city
  records as multiuse trails or paths (the Veirs Mill correction again). OSM
  edits upstream are the durable fix; the candidate list is
  `reports/data-comparison/baltimore-facility-candidates.csv`. Credit "City of
  Baltimore, Open Baltimore".

Both files keep within the rows the owner was shown and approved
(`reports/data-comparison/owner-approved-override-ways.json`, the proposal at
commit 318708b: 411 MoCo ways; 264 Baltimore stress and 180 access rows), so a
re-derivation never adds a way the owner did not see (review r2). What the
re-derivation drops or changes is listed in the two reports for the owner: MoCo
409 of 411 (Clarksville Pike 5268038 and Ridge Road 50832512 no longer match a
county record); Baltimore 256 of 264 (eight approved rows no longer qualify, N
Charles Street 970453181 now LTS 2 with the facility where LTS 3 was approved,
and five new ways held back).

N Charles Street 970453181 stays at the derived LTS 2. Asked whether to keep
the approved LTS 3 or the tier the classifier now derives with the city's
facility tagged, the owner answered (OWNER-DECISIONS 198, 2026-10-02): "LTS 2
as derived (Recommended)". Its row in the Baltimore file is tier 2 and is not
changed back.

## Block corrections, and the file of 2026-10-02

A file may also correct an agency street block's record rather than a way: a
top-level `agency_blocks` list, each entry `{"blockkey": <the layer's key for
the block, DC's BLOCKKEY>, "routename": <its ROUTENAME>, "withhold": ["speed"],
"reason": ..., "evidence": ...}` (`street` and `ways` are for the reader). The
rebuild reads it from its image (`routemaker.agency_roads.withheld_blocks`,
found among the installed blocks by `resolve_withheld`, through
`pipeline.conflation.road_facts_by_way`, which the analysis scripts share): the
withheld fact is not applied to any way matched to the block, so OSM's value
stands and the tier follows from it by the same tables as every other road.
Only the posted speed may be withheld; a malformed entry refuses the rebuild's
matching rather than being skipped. The block is named by BLOCKKEY, not by its
installed id: that id (`dc-<OBJECTID>-<part>`) is built from OBJECTID, the
ArcGIS row number, which DC's republishing may reassign (gate review,
should-fix 1). The ROUTENAME is a check a reader can see: an entry whose key
names no installed block, or a block on another street, withholds nothing, and
the rebuild's log warns "owner's block correction not applied" with the key, so
a reinstalled layer cannot quietly give the block's value back. The installer
keeps the key (`RoadFacts.block_key`); a `roadway.json` installed by an earlier
version has none, so the street blocks are reinstalled
(`scripts/install_reference_data.py --roadway-block`) before the rebuild that
should apply these files. This is a block list and not stress rows because
OSM's way ids change when a way is split, and a stress row would have held the
tier while the classifier still read the block's speed. A file with only
`agency_blocks` has `"rows": []`, and the loader says it has nothing to load,
so step 7 of "First rebuild on a fresh host" can still be given every file. It
takes effect at the next rebuild after the image carrying it is deployed. The
discrepancy report lists the ways as not applied, "owner override".

- `2026-10-02-owner-canal-whitehurst.json` (OWNER-DECISIONS 197, verbatim: "DC
  records of 20 mph on Canal Rd NW (block dc-4633425-0) and the Whitehurst Fwy
  (dc-4636053-0), owner 2026-10-02: "Override: keep LTS 4 (Recommended)". A
  stress override holds them at the OSM speeds and LTS 4, and they stay listed in
  the discrepancy report."): DC's 20 mph is withheld on both blocks, so OSM's
  posted 35 mph stands. Canal Road NW's five trunk ways (0.38 mi [612 m]) are LTS
  4 again, not 3; the Whitehurst Freeway, a motorway, is LTS 4 either way and now
  reads OSM's speed. 17 ways are listed in the discrepancy report as owner
  overrides.

## Fingerprints, and ways OSM splits (decision 282)

An override names a way by OSM id, and ids do not last: a mapper splits or merges the way
and the next extract no longer has it. Every row therefore carries a `fingerprint` of the
way it was written for, `{"name", "highway", "length_m", "line"}` (`line` is the
simplified polyline as `lon,lat` pairs; `pipeline.rematch.fingerprint_of`). The database
row holds none, so the rebuild reads it from its image's copy of these files by kind and
way id (`rematch.load_fingerprints`); `load_access_overrides` checks a fingerprint and
keeps it in the file. A row typed into the admin has none and cannot be re-matched.
`scripts/analysis/backfill_override_fingerprints.py --pbf <extract> [--write]` adds them
read-only from an extract; new files should carry them from the start.

When an approved row's way is missing from the extract, APPLY_OVERRIDES
(`rematch.resolve`) looks for the ways of the same street name and highway class that
now lie along the stored line (within 20 ft (6 m), 90% of each way's length, 90% of the
line covered, each within 30 degrees of the line's direction, and together within a
factor of 1.25 of its length) and applies the row to all of them, but only when that is
unambiguous: not when two ways run side by side along it (also on a line shorter than
49 ft (15 m)), nor when another way of that name overlaps it
beyond an end-on neighbour, nor when a target already carries a different row. Every
row that was missing is listed with its outcome (`rematched`, `covered`, `failed` and
why) in `<DATA_ROOT>/rebuild/reports/override-rematch.md` and `.csv`, and summarised in
the log line and the run row. A failed row is left as it was, so it is still counted as
matching no way; nothing is dropped quietly. Rows whose way is present but no longer
looks like its fingerprint are listed as `drifted` and still apply.

A file that re-points a row at new ways keeps the old way in a top-level `superseded`
list, with `replaced_by` and the old way's fingerprint, because the row already loaded
in the database still names it: delete that row in the admin when loading the file
(the new rows carry the same value, so until then the re-match reports it `covered` or
`failed`, never twice applied).

- `2026-10-01-owner-baltimore-facilities.json`, Harford Road (decision 282a): way
  424993005 (43 ft, 13.2 m) was redrawn in the 2026-10-03 extract as 213 ft (64.8 m) of
  new ways: 1562097553 and 1562097555, the two carriageways of a short divided section,
  and 1562097556 continuing north. Its row is re-pointed at all three, at 39.3468 N,
  76.5662 W, each checked against
  Open Baltimore record 634 (Harford Rd, Montebello Ter to Echodale Ave): the three lie
  within 9.3, 6.3 and 5.7 m of its line (`tests/data/open_baltimore_record_634.json`).
  The generic re-match declines this one, as it should: the junction was redrawn, so
  other Harford Road ways overlap the old line without lying along it.
