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
