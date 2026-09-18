# Round 10 — Database / scheduler / rebuild operations — REVISE (1 blocking)

Reviewed at `0d79759`. All twenty wave-8 items closed by reversion and execution. The restore
runbook walked against the code: the archive carries the live segment schema, `django_migrations`,
the Procrastinate tables and the run rows; a restore into an empty database gives zero errors, also
when PostGIS is already installed; the deployment epoch survives the restore as the source
deployment's, which is what makes the runbook's "it will page for a while" paragraph true.

**What would change my verdict:** the two guide passages and the test that pins one of them
corrected to the mounts `api` now has, and `rollback_rebuild` refusing in a container whose tiles
it cannot write — or the reachability recorded in §7 with the state it leaves named.

## BLOCKING
**B10-1.** Both guides still say `api` mounts no part of the data volume and that `rollback_rebuild`
there refuses harmlessly with "no previous tiles"; a doc test pins the sentence and says it "is not
going to be fixed". Wave 8 gave `api` `DATA_ROOT=/data` and the tiles read-only, so `TILES_DIR`
there is the real tree. Executed in a container shaped like `api`: the dry run does not refuse;
`--confirm` runs `rollback_swap()` before the tile demotion, both renames commit, the first demote
fails on the read-only mount, and the undo re-swaps — unless an ordinary reader holds `ACCESS
SHARE` on the segment relation, which the api process itself does all day, in which case the
re-swap loses five attempts and raises `SwapLockTimeout`. End state read back: schemas `live` and
`staging` (no `live_old`), `live.segment` = last week's rows, tiles `current` = this week's,
upstream rows = this week's, no rollback target; the served build's rows now sit in `staging`,
which the next rebuild's first stage drops. A wave-8 regression: the documented refusal is gone
while the documentation, and a test asserting the sentence, both still claim it.

## SHOULD-FIX
- **S10-1.** Nothing tells the operator what to do after a `SwapUndoIncomplete`; `rollback_rebuild`
  refuses on a half-restored deployment, so the alert names the damage and nothing names the repair.
- **S10-2.** `unwedge_job` prints queue-pickup advice after saying the job landed `failed`.

## NIT
A test fixture says `nightly_backup` takes no queueing lock (it does); the deployment guide's bold
present-tense no-mount claim; `disk_headroom` guards a missing `TILES_DIR` but not `disk_usage`
raising on a stale bind.

Weighed and upheld: `unmeasured` as exit 1; the read-only bind on `api`; `SwapUndoIncomplete`
terminal; `failure_detail`'s dedupe and bound; the `<` on part-file instants; the epoch after a
restore.
