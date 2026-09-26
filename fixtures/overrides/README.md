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
Discord sign-in, so load overrides after that.

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
