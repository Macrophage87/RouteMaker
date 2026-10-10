# Overrides: access against stress

[Index](README.md). An override is an approved row in the `Override` table
(`src/core/models.py`). Unapproved rows never leave the database: the query filters
them out (`load_approved`, `src/pipeline/overrides.py:320-343`). The full file format
and the history of each file are in `fixtures/overrides/README.md`. This page is
the model.

## Three kinds, three places

`HANDLED_KINDS` (`overrides.py:99`). An approved row of any other kind refuses the
rebuild (`src/pipeline/run.py:1986-2004`).

| Kind | What it changes | When | Lines |
|---|---|---|---|
| `access` | Tags on the way, before the transform: only `bicycle`, `bicycle:forward`, `bicycle:backward`, `access`, `oneway:bicycle`, `motor_vehicle` | Before Valhalla's tag transform, so every graph variant derives access from the corrected tag | `ACCESS_KEYS` `:55-57`; `apply_access` `:346-403` |
| `stress` | The way's tier and its adjustment record | After classification. A tier cannot be fed back through the classifier as tags | `apply_stress` `:406-458`; value rules `:106-192` |
| `jurisdiction` | The way's authority, not a routing input | After classification | `apply_jurisdiction` |

Access and stress are separate claims. A way may carry one row of each, and the
Dupont underpass file does: `bicycle=yes` plus a tier-4 stress row. An access row
decides whether a bicycle may ride, and a stress row decides how stressful the ride
is. `motor_vehicle=no` (`:58-65`) is the one access key about cars. It makes the road
a path for the facility class, and then the car-free rule makes it LTS 1
([classification.md](classification.md)).

## A stress row's value

`STRESS_REQUIRED_KEYS` and `STRESS_KEYS` (`overrides.py:110-113`), validated by
`stress_value_problem` (`:134-192`) in both the loader and the rebuild.

| Key | Meaning |
|---|---|
| `tier` | Integer 1-5 (`:119`, `:155-159`). It may be below the classifier's: a down-adjustment ("down adjust a road if this is the better route among similar routes"). Half steps are **planned** (the editor stores the lower level plus a flag; HALF-STEP-EDITOR-plan section 4.1). |
| `at_least` | Optional. `true` makes the row a **floor**: the way gets max(its tier at that point, `tier`), where its tier at that point is the classifier's after the curated lanes, the corridors and any earlier row for the way (`:436-443`). A way already at or above it keeps its own tier, its rule and no adjustment, and the row is not counted as applied (`:113-118`, `:438-444`; OWNER-DECISIONS 445a-c). |
| `adjustment_id` | Lower-case words joined by hyphens, at most 64 characters (`:121-122`), shared by every way of one stretch and stable across rebuilds. |
| `category` | `speed`, `road_conditions`, `driver_behaviour`, `intersection`, `sightlines`, `better_among_alternatives`, `other` (`src/routemaker/stress.py:326-334`). |
| `visibility` | `public` or `hidden`. |
| `annotation_status` | `proposed` or `approved`. Only public and approved adjustments show their reason (`StressAdjustment.is_shown`, `stress.py:376-379`). Everything else is published as "adjusted" with its id (`exposed`, `:381-394`). |
| `display` | `route_only` (only in the summary of a route over the stretch) or `map` (that, and on a map click). |
| `public_note` | Optional, at most 200 characters. It describes the road and its traffic, never a neighborhood or its people. Words such a note would most likely use are refused (`:123-131`, `:180-191`). |

A row typed into the admin as `{"tier": n}` still sets the tier, as a hidden
adjustment `way-<id>` (`stress_adjustment`, `overrides.py:195-236`). The row's own
`reason` is the owner's words. It stays in the row and its audit trail and is never
shown to riders (`overrides.py:447-452`).

## Order of precedence for a way's tier

1. The classifier (`stress.classify`).
2. The curated bike lane's owner tier, then named corridors (`run.py:1786-1826`).
3. Approved stress rows: a row that sets the tier wins; a floor only raises
   (`run.py:2026`).
4. Car-free for good becomes LTS 1, except where a curated stress row set the tier
   (`run.py:1383-`).

An agency **block correction** (`agency_blocks` in a file) is not a row. It withholds
one fact of a DC Roadway Block record (only the posted speed), so OSM's value stands
and the classifier rates the way from it (`fixtures/overrides/README.md`, "Block
corrections"; `src/routemaker/agency_roads.py`, `withheld_blocks`, `resolve_withheld`;
`run.py:1598-1611`).

## Files, the loader and retire lists

- Owner decisions made in conversation are checked in as versioned files in
  `fixtures/overrides/` (`{"version": 1, "decided", "decided_by", "rows": [...]}`).
- `manage.py load_access_overrides` (alias `load_overrides`,
  `src/core/management/commands/load_overrides.py`) loads one file from standard input.
  It is **dry unless `--confirm`**. It attributes the rows to the instance admin named
  by `--actor`, which is checked to be an active instance admin but is not
  authenticated, and every audit entry says so (`load_access_overrides.py:11-21`, `:78`,
  `:200-231`). It writes each row approved, with audit entries for the add and the
  approval. It is idempotent, and it refuses the whole file before writing anything on a
  malformed row, a disallowed key, a way named twice, or an approved row on the same way
  that disagrees.
- `retire`: a top-level list of `{"kind", "osm_way_id", "value", "reason"}`. Each entry
  is a row as it was loaded, plus the decision that withdraws it. The loader deletes
  every approved or proposed row of that kind, way and exact value, audited as a delete
  with that reason, before it plans the file's own rows. A replacing row on the same way
  is then not refused as a conflict. A row already gone is `absent`. A file may retire
  rows and load none (`load_access_overrides.py:50-57`, `:156-197`, `:329-356`).
- `superseded`: a file that re-points a row at new ways keeps the old way listed with
  `replaced_by`. The old database row must then be deleted in the admin
  (`fixtures/overrides/README.md`, "Fingerprints").
- **Undo**: `approved` is read-only in the admin, so a loaded row is deleted (audited),
  and a deliberate removal also takes the row out of the file in a reviewed commit, or
  the next load recreates it.
- Rows take effect at the **next rebuild**. The routers keep what they were built with
  until then. Some files depend on others and must be loaded in order (the crossings
  install first, then the east-of-the-Anacostia file before the military reopenings);
  docs/OPERATIONS.md, "A deploy that changes the crossings fixture or loads access
  overrides", has the procedure.

## The owner's sign-off rule (453a)

- **Overrides are never created or loaded automatically.** No heuristic, script or
  agent writes override rows on its own initiative.
- The owner's acceptance of specific overrides **in chat is the sign-off**. An operator
  may then load them: dry run first, then `--confirm` as the instance admin, stopping on
  any mismatch.
- The planned half-step editor keeps the rule. An instance admin's edit is that
  admin's own act. A signed-in rider's suggestion goes to a separate table and is never
  applied automatically: an admin approves, declines or (460.5) sends it to Discord for
  discussion (HALF-STEP-EDITOR-plan sections 5.1-5.3). **Planned.**

## Re-matching by fingerprint (OWNER-DECISIONS 282)

OSM way ids do not last: a mapper splits or merges a way. Each row in a file carries
a `fingerprint` of its way: `name`, `highway`, `length_m` and a simplified `line`
(`src/pipeline/rematch.py`, `fingerprint_of`). The database row has none, so the
rebuild reads it from the image's copy of the files (`rematch.load_fingerprints`).
When an approved row's way is missing, `rematch.resolve` (`rematch.py:534-`, called at
`run.py:2010`) looks for ways of the same name and class along the stored line. Its
constants are at `rematch.py:63-95`:

- within 20 ft [6 m] of the line (`TOLERANCE_M`);
- 90% of each way's length on it and 90% of the line covered;
- each within 30 degrees of the line's direction;
- together within 1.25 times its length.

It applies the row to all of them only when that is unambiguous. It declines when two
ways run side by side, when another way of the name overlaps it beyond an end-on
neighbor, or when a target already carries a different row. Every missing row is
reported as `rematched`, `covered`, `failed` or `drifted` in
`override-rematch.md`/`.csv` in the rebuild's report directory and summarized in the
run row. A failed row is left as it was and still counted as matching no way. A row
typed into the admin has no fingerprint and cannot be re-matched. Nor can the
crosswalk-links file's rows, which by decision 442 carry way ids only.
